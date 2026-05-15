import streamlit as st
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
import pikepdf

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ═══════════════════════════════════════════════════════════════════════════════

FUENTES = {
    "Times Roman":      "Times-Roman",
    "Times Bold":       "Times-Bold",
    "Helvetica":        "Helvetica",
    "Helvetica Bold":   "Helvetica-Bold",
    "Courier":          "Courier",
}


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN 1 — NUMERACIÓN
# Genera un PDF nuevo con una página por folio.
# Cada página muestra "{texto} {número}" centrado horizontalmente,
# a la distancia elegida desde el borde superior.
# ═══════════════════════════════════════════════════════════════════════════════

def generar_numeracion(texto, folio_inicio, folio_fin, fuente, tamano, dist_top_mm):
    buf = io.BytesIO()
    w, h = A4
    c = canvas.Canvas(buf, pagesize=A4)

    for folio in range(folio_inicio, folio_fin + 1):
        c.setFont(fuente, tamano)
        c.drawCentredString(
            w / 2,
            h - dist_top_mm * mm,
            "{} {}".format(texto, folio),
        )
        c.showPage()

    c.save()
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN 2 — MARGEN ANCHO
# Agrega margen de encuadernación alternante:
#   • Páginas impares (1, 3, 5…): margen a la IZQUIERDA
#   • Páginas pares (2, 4, 6…):  margen a la DERECHA
# El contenido se escala proporcionalmente y se centra verticalmente.
# ═══════════════════════════════════════════════════════════════════════════════

def agregar_margen(archivo, margen_mm):
    original = pikepdf.Pdf.open(archivo)
    salida = pikepdf.Pdf.new()
    margen_pt = margen_mm * mm

    # Copiar todas las páginas al PDF de salida
    for page in original.pages:
        salida.pages.append(page)

    for i, page in enumerate(salida.pages):
        mb = page.MediaBox
        x0, y0 = float(mb[0]), float(mb[1])
        x1, y1 = float(mb[2]), float(mb[3])
        ancho = x1 - x0
        alto = y1 - y0

        # Escala uniforme para que el contenido quepa sin el ancho del margen
        escala = (ancho - margen_pt) / ancho

        # Centrado vertical: mismo espacio arriba y abajo
        ty = y0 * (1 - escala) + alto * (1 - escala) / 2

        # Alternancia: impares → margen izquierdo, pares → margen derecho
        if i % 2 == 0:
            tx = margen_pt + x0 * (1 - escala)
        else:
            tx = x0 * (1 - escala)

        # Leer contenido existente de la página
        contents = page.get("/Contents")
        if contents is None:
            data = b""
        elif isinstance(contents, pikepdf.Array):
            data = b"".join(s.read_bytes() for s in contents)
        else:
            data = contents.read_bytes()

        # Envolver con la transformación: q cm … contenido Q
        header = "q\n{:.10f} 0 0 {:.10f} {:.6f} {:.6f} cm\n".format(
            escala, escala, tx, ty
        ).encode()
        page.Contents = salida.make_stream(header + data + b"\nQ\n")

    out = io.BytesIO()
    salida.save(out)
    out.seek(0)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN 3 — TEXTO INTERLINEADO
# Inserta un renglón de texto en la página 1 del PDF.
# Posición absoluta (desde izquierda, desde arriba), tipografía,
# tamaño y espaciado entre letras (tracking) controlados por el usuario.
# Se usa un Form XObject para aislar recursos y evitar conflictos de fuentes.
# ═══════════════════════════════════════════════════════════════════════════════

def agregar_texto(archivo, texto, dist_izq_mm, dist_top_mm,
                  fuente, tamano, tracking):
    original = pikepdf.Pdf.open(archivo)
    salida = pikepdf.Pdf.new()

    for page in original.pages:
        salida.pages.append(page)

    page = salida.pages[0]
    mb = page.MediaBox
    w = float(mb[2]) - float(mb[0])
    h = float(mb[3]) - float(mb[1])

    # ── Crear overlay con reportlab ────────────────────────────────────
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setFont(fuente, tamano)
    c.setCharSpace(tracking)
    c.drawString(dist_izq_mm * mm, h - dist_top_mm * mm, texto)
    c.showPage()
    c.save()
    buf.seek(0)

    # ── Leer overlay como Form XObject ─────────────────────────────────
    overlay = pikepdf.Pdf.open(buf)
    overlay_page = overlay.pages[0]

    oc = overlay_page.Contents
    if isinstance(oc, pikepdf.Array):
        overlay_data = b"".join(s.read_bytes() for s in oc)
    else:
        overlay_data = oc.read_bytes()

    form = salida.make_stream(overlay_data)
    form["/Type"]    = pikepdf.Name("/XObject")
    form["/Subtype"] = pikepdf.Name("/Form")
    form["/BBox"]    = pikepdf.Array([
        float(overlay_page.MediaBox[0]),
        float(overlay_page.MediaBox[1]),
        float(overlay_page.MediaBox[2]),
        float(overlay_page.MediaBox[3]),
    ])

    if "/Resources" in overlay_page:
        form["/Resources"] = salida.copy_foreign(overlay_page["/Resources"])

    # ── Registrar XObject en la página principal ───────────────────────
    if "/Resources" not in page:
        page["/Resources"] = pikepdf.Dictionary()
    res = page["/Resources"]
    if "/XObject" not in res:
        res["/XObject"] = pikepdf.Dictionary()
    res["/XObject"]["/TextMark"] = form

    # ── Agregar comando de dibujo al contenido existente ───────────────
    ec = page.Contents
    if isinstance(ec, pikepdf.Array):
        existing = b"".join(s.read_bytes() for s in ec)
    else:
        existing = ec.read_bytes()

    page.Contents = salida.make_stream(existing + b"\nq\n/TextMark Do\nQ\n")

    out = io.BytesIO()
    salida.save(out)
    out.seek(0)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# INTERFAZ STREAMLIT — TRES PESTAÑAS INDEPENDIENTES
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Procesador Notarial",
    page_icon="📜",
    layout="centered",
)

st.title("Sistema de Ajuste de Protocolo")
st.caption(
    "Tres herramientas independientes para adecuar documentos al formato notarial."
)
st.divider()

tab_num, tab_mar, tab_txt = st.tabs([
    "📄  Numeración",
    "📐  Margen ancho",
    "✏️  Texto",
])


# ─── TAB 1: NUMERACIÓN ──────────────────────────────────────────────────────

with tab_num:
    st.subheader("Generar foliación")
    st.markdown(
        "Genera un PDF nuevo con una página por folio. "
        "**No requiere archivo de entrada.**"
    )

    c1, c2 = st.columns(2)
    with c1:
        n_texto  = st.text_input("Texto del folio", value="Folio", key="n_txt")
        n_fuente = st.selectbox("Tipografía", list(FUENTES.keys()), key="n_fnt")
        n_fini   = st.number_input("Primer folio",  min_value=1, value=1,  key="n_ini")
    with c2:
        n_tam    = st.number_input("Tamaño de fuente (pt)", min_value=6,
                                   max_value=72, value=14, key="n_tam")
        n_dist   = st.number_input("Distancia desde arriba (mm)", min_value=5,
                                   max_value=250, value=25, key="n_dst")
        n_ffin   = st.number_input("Último folio", min_value=1, value=10, key="n_fin")

    if st.button("Generar PDF", key="b_num", use_container_width=True):
        if n_ffin < n_fini:
            st.error("El último folio debe ser mayor o igual al primero.")
        else:
            with st.spinner("Generando foliación…"):
                res = generar_numeracion(
                    n_texto, n_fini, n_ffin,
                    FUENTES[n_fuente], n_tam, n_dist,
                )
            total = n_ffin - n_fini + 1
            st.success("{} página(s) generadas — de \"{} {}\" a \"{} {}\".".format(
                total, n_texto, n_fini, n_texto, n_ffin,
            ))
            st.download_button(
                label="Descargar foliación",
                data=res.getvalue(),
                file_name="foliacion.pdf",
                mime="application/pdf",
                use_container_width=True,
            )


# ─── TAB 2: MARGEN ANCHO ────────────────────────────────────────────────────

with tab_mar:
    st.subheader("Agregar margen de encuadernación")
    st.markdown(
        "Margen alternante: **izquierda** en páginas impares (1, 3, 5…), "
        "**derecha** en pares (2, 4, 6…). "
        "El contenido se escala proporcionalmente y queda centrado verticalmente."
    )

    arch_m = st.file_uploader("Subir PDF", type=["pdf"], key="u_m")
    mm_val = st.number_input("Margen (mm)", min_value=5, max_value=100,
                             value=40, key="m_mm")

    # Vista previa del documento
    if arch_m:
        try:
            tmp = pikepdf.Pdf.open(arch_m)
            mb0 = tmp.pages[0].MediaBox
            w0  = (float(mb0[2]) - float(mb0[0])) / mm
            h0  = (float(mb0[3]) - float(mb0[1])) / mm
            esc = (w0 - mm_val) / w0 * 100
            tmp.close()
            st.info(
                "{} página(s) — {:.0f} × {:.0f} mm  →  escala resultante: {:.1f}%".format(
                    len(tmp.pages) if hasattr(tmp, 'pages') else "?", w0, h0, esc
                )
            )
        except Exception:
            st.warning("No se pudo leer la información del documento.")
        arch_m.seek(0)

    if st.button("Aplicar margen", key="b_mar", use_container_width=True):
        if arch_m is None:
            st.warning("Subí un archivo PDF primero.")
        else:
            with st.spinner("Procesando…"):
                res = agregar_margen(arch_m, mm_val)
            st.success("Margen de {} mm aplicado.".format(mm_val))
            st.download_button(
                label="Descargar PDF con margen",
                data=res.getvalue(),
                file_name="margen_{}mm.pdf".format(mm_val),
                mime="application/pdf",
                use_container_width=True,
            )


# ─── TAB 3: TEXTO INTERLINEADO ──────────────────────────────────────────────

with tab_txt:
    st.subheader("Insertar texto en página 1")
    st.markdown(
        "Coloca un renglón de texto en la posición exacta que indiques. "
        "Solo afecta la primera página."
    )

    arch_t = st.file_uploader("Subir PDF", type=["pdf"], key="u_t")
    t_texto = st.text_input("Texto a insertar", value="", key="t_val",
                            placeholder="Ej.: Sello notarial — Escribanía N° 5")

    c1, c2 = st.columns(2)
    with c1:
        t_izq    = st.number_input("Desde izquierda (mm)", min_value=0,
                                   max_value=200, value=20, key="t_izq")
        t_fuente = st.selectbox("Tipografía", list(FUENTES.keys()), key="t_fnt")
        t_track  = st.slider("Espaciado entre letras (pt)",
                             min_value=-5, max_value=5, value=0, key="t_trk")
    with c2:
        t_top    = st.number_input("Desde arriba (mm)", min_value=0,
                                   max_value=200, value=20, key="t_top")
        t_tam    = st.slider("Tamaño de fuente (pt)",
                             min_value=8, max_value=12, value=10, key="t_tam")

    if st.button("Insertar texto", key="b_txt", use_container_width=True):
        if arch_t is None:
            st.warning("Subí un archivo PDF primero.")
        elif not t_texto.strip():
            st.warning("Ingresá el texto a insertar.")
        else:
            with st.spinner("Procesando…"):
                res = agregar_texto(
                    arch_t, t_texto,
                    t_izq, t_top,
                    FUENTES[t_fuente], t_tam, t_track,
                )
            st.success("Texto insertado en la página 1.")
            st.download_button(
                label="Descargar PDF con texto",
                data=res.getvalue(),
                file_name="con_texto.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
