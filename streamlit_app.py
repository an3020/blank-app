import streamlit as st
import io
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
import pikepdf

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

MARGEN_COSTURA_MM = 60          # Margen izquierdo requerido (mm)
MARGEN_FOLIO     = 12 * mm      # Separación del folio respecto al borde
TAM_FOLIO        = 13           # Tamaño de fuente del folio
TAM_SELLO        = 8            # Tamaño de fuente del sello


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE PROCESAMIENTO
# ═══════════════════════════════════════════════════════════════════════════════

def crear_overlay_folios(paginas, posicion, sello=None):
    """
    Genera un PDF de overlay con una página por cada entrada,
    conteniendo el número de folio y el sello opcional.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf)

    for info in paginas:
        w, h = info["ancho"], info["alto"]
        c.setPageSize((w, h))

        # ── Número de folio ──────────────────────────────────────────────
        texto = "FO. {}".format(info["folio"])
        c.setFont("Helvetica-Bold", TAM_FOLIO)
        pad = MARGEN_FOLIO

        posiciones = {
            "Superior derecha":   (w - pad, h - pad, "R"),
            "Superior izquierda": (pad,     h - pad, "L"),
            "Inferior derecha":   (w - pad, pad,     "R"),
            "Inferior izquierda": (pad,     pad,     "L"),
        }
        px, py, al = posiciones.get(posicion, posiciones["Superior derecha"])

        # Fondo semitransparente para legibilidad sobre cualquier fondo
        tw = c.stringWidth(texto, "Helvetica-Bold", TAM_FOLIO)
        rx = (px - tw - 5) if al == "R" else (px - 5)
        c.saveState()
        c.setFillColor(colors.Color(1, 1, 1, 0.85))
        c.roundRect(rx, py - 4, tw + 10, TAM_FOLIO + 8, 3, fill=1, stroke=0)
        c.setFillColor(colors.black)
        if al == "R":
            c.drawRightString(px, py, texto)
        else:
            c.drawString(px, py, texto)
        c.restoreState()

        # ── Sello notarial (opcional) ────────────────────────────────────
        if sello:
            c.saveState()
            c.setFont("Helvetica-Oblique", TAM_SELLO)
            c.setFillColor(colors.Color(0.35, 0.35, 0.35))
            c.drawCentredString(w / 2, 8 * mm, sello)
            c.restoreState()

        c.showPage()

    c.save()
    buf.seek(0)
    return buf


def transformar_pagina(page, pdf, margen_pt):
    """
    Modifica el contenido de una página aplicando:
      - Escala uniforme para que quepa en (ancho - margen).
      - Desplazamiento horizontal de 'margen_pt' puntos a la derecha.
      - Anclaje en la esquina superior para preservar encabezados.

    Retorna (ancho, alto, escala).
    """
    mb = page.MediaBox
    x0, y0 = float(mb[0]), float(mb[1])
    x1, y1 = float(mb[2]), float(mb[3])
    ancho = x1 - x0
    alto  = y1 - y0

    # Escala uniforme: el contenido quepa en el espacio restante
    escala = (x1 - margen_pt) / ancho

    # Desplazamiento: empuja el contenido a la derecha (ancla superior)
    tx = margen_pt - escala * x0
    ty = y1 * (1 - escala)

    # Leer contenido existente (puede ser un stream o un array de streams)
    contents = page.get("/Contents")
    if contents is None:
        data = b""
    elif isinstance(contents, pikepdf.Array):
        data = b"".join(s.read_bytes() for s in contents)
    else:
        data = contents.read_bytes()

    # Envolver con la transformación: q cm ... contenido Q
    header = "q\n{:.10f} 0 0 {:.10f} {:.6f} {:.6f} cm\n".format(
        escala, escala, tx, ty
    ).encode()
    page.Contents = pdf.make_stream(header + data + b"\nQ\n")

    return ancho, alto, escala


def fusionar_overlay(main_page, overlay_page, pdf):
    """
    Superpone el contenido de overlay_page sobre main_page
    utilizando un Form XObject, evitando conflictos de recursos.
    """
    # Extraer bytes del overlay
    oc = overlay_page.Contents
    if isinstance(oc, pikepdf.Array):
        overlay_data = b"".join(s.read_bytes() for s in oc)
    else:
        overlay_data = oc.read_bytes()

    # Crear Form XObject
    form = pdf.make_stream(overlay_data)
    form["/Type"]    = pikepdf.Name("/XObject")
    form["/Subtype"] = pikepdf.Name("/Form")
    form["/BBox"]    = pikepdf.Array([
        float(overlay_page.MediaBox[0]),
        float(overlay_page.MediaBox[1]),
        float(overlay_page.MediaBox[2]),
        float(overlay_page.MediaBox[3]),
    ])

    # Copiar recursos del overlay (fuentes, etc.) al XObject
    if "/Resources" in overlay_page:
        form["/Resources"] = pdf.copy_foreign(overlay_page["/Resources"])

    # Registrar XObject en los recursos de la página principal
    if "/Resources" not in main_page:
        main_page["/Resources"] = pikepdf.Dictionary()
    res = main_page["/Resources"]
    if "/XObject" not in res:
        res["/XObject"] = pikepdf.Dictionary()
    res["/XObject"]["/FolioMark"] = form

    # Agregar comando de dibujo al final del contenido de la página
    ec = main_page.Contents
    if isinstance(ec, pikepdf.Array):
        existing = b"".join(s.read_bytes() for s in ec)
    else:
        existing = ec.read_bytes()

    main_page.Contents = pdf.make_stream(
        existing + b"\nq\n/FolioMark Do\nQ\n"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def procesar_pdf(archivo, folio_inicio, posicion, sello=None):
    """
    Pipeline completo:
      1. Copiar páginas al PDF de salida.
      2. Transformar contenido (margen + escala).
      3. Crear overlay con folios y sello.
      4. Fusionar overlay en cada página.
    Retorna (BytesIO con el PDF resultante, lista de info por página).
    """
    original = pikepdf.Pdf.open(archivo)
    salida   = pikepdf.Pdf.new()
    margen   = MARGEN_COSTURA_MM * mm
    n        = len(original.pages)

    # 1. Copiar páginas
    for page in original.pages:
        salida.pages.append(page)

    # 2. Transformar contenido de cada página
    paginas = []
    for i in range(n):
        page = salida.pages[i]
        ancho, alto, escala = transformar_pagina(page, salida, margen)
        paginas.append({
            "ancho": ancho,
            "alto": alto,
            "folio": folio_inicio + i,
            "escala": escala,
        })

    # 3. Crear overlay de folios
    overlay_buf = crear_overlay_folios(paginas, posicion, sello)
    overlay_pdf = pikepdf.Pdf.open(overlay_buf)

    # 4. Fusionar overlay en cada página
    for i in range(n):
        fusionar_overlay(salida.pages[i], overlay_pdf.pages[i], salida)

    # 5. Guardar resultado
    out = io.BytesIO()
    salida.save(out)
    out.seek(0)
    return out, paginas


# ═══════════════════════════════════════════════════════════════════════════════
# INTERFAZ STREAMLIT
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Procesador Notarial",
    page_icon="📜",
    layout="centered",
)

st.title("Sistema de Ajuste de Protocolo")
st.caption(
    "Adecuación de PDFs al formato notarial: "
    "margen de costura de 60 mm, escala proporcional y foliado automático."
)
st.divider()

# ── Carga de archivo ─────────────────────────────────────────────────────────
archivo = st.file_uploader("Subir documento PDF", type=["pdf"])

if archivo:
    try:
        tmp   = pikepdf.Pdf.open(archivo)
        n_pag = len(tmp.pages)
        mb0   = tmp.pages[0].MediaBox
        w0    = (float(mb0[2]) - float(mb0[0])) / mm
        h0    = (float(mb0[3]) - float(mb0[1])) / mm
        tmp.close()
        st.info(
            "Documento cargado: **{} página(s)** — {:.0f} × {:.0f} mm".format(
                n_pag, w0, h0
            )
        )
    except Exception:
        st.warning("No se pudo leer la información del documento.")
    archivo.seek(0)

st.divider()

# ── Parámetros ───────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    folio_inicio = st.number_input("Folio inicial", min_value=1, value=1, step=1)
with col2:
    posicion = st.selectbox("Posición del folio", [
        "Superior derecha",
        "Superior izquierda",
        "Inferior derecha",
        "Inferior izquierda",
    ])

usar_sello = st.toggle("Agregar sello notarial")
sello_texto = None
if usar_sello:
    sello_texto = st.text_input(
        "Texto del sello", value="Escribanía N° XX — Ciudad"
    )

st.divider()

# ── Procesamiento ────────────────────────────────────────────────────────────
if st.button("Procesar Documento", type="primary", use_container_width=True):
    if archivo is None:
        st.warning("Subí un archivo PDF para continuar.")
    else:
        try:
            with st.spinner("Procesando documento..."):
                resultado, paginas = procesar_pdf(
                    archivo, folio_inicio, posicion, sello_texto
                )

            st.success("¡Documento procesado correctamente!")

            # Métricas
            m1, m2, m3 = st.columns(3)
            m1.metric("Páginas", len(paginas))
            m2.metric("Primer folio", "FO. {}".format(paginas[0]["folio"]))
            m3.metric("Último folio", "FO. {}".format(paginas[-1]["folio"]))

            # Detalles técnicos
            with st.expander("Detalles del procesamiento"):
                p = paginas[0]
                st.write(
                    "Dimensiones originales: {:.0f} × {:.0f} mm".format(
                        p["ancho"] / mm, p["alto"] / mm
                    )
                )
                st.write("Margen de costura: {} mm".format(MARGEN_COSTURA_MM))
                cont_w = (p["ancho"] - MARGEN_COSTURA_MM * mm) / mm
                cont_h = p["alto"] / mm * p["escala"]
                st.write(
                    "Área de contenido: {:.0f} × {:.0f} mm".format(cont_w, cont_h)
                )
                st.write("Escala aplicada: {:.1f}%".format(p["escala"] * 100))

            # Descarga
            st.download_button(
                label="Descargar PDF procesado",
                data=resultado.getvalue(),
                file_name="protocolo_corregido.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

        except Exception as e:
            st.error("Error al procesar el documento: {}".format(e))
            import traceback
            with st.expander("Ver detalle técnico"):
                st.code(traceback.format_exc())
