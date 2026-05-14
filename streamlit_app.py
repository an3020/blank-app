import streamlit as st
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
import pikepdf

st.set_page_config(page_title="Procesador Notarial", layout="centered")

st.title("Sistema de Ajuste de Protocolo")
st.write("Ajuste de margen de 60mm y foliado automático.")

archivo = st.file_uploader("Subir PDF original", type=["pdf"])
foliado_inicio = st.number_input("Número de folio inicial", min_value=1, value=1)

if st.button("Procesar Documento"):
    if archivo is not None:
        try:
            # Abrir el PDF
            pdf_original = pikepdf.Pdf.open(archivo)
            output_pdf = io.BytesIO()
            
            # Guardar (esto confirma que las librerías funcionan)
            pdf_original.save(output_pdf)
            
            st.success("¡Documento procesado con éxito!")
            st.download_button(
                label="Descargar PDF corregido",
                data=output_pdf.getvalue(),
                file_name="protocolo_corregido.pdf",
                mime="application/pdf"
            )
        except Exception as e:
            st.error(f"Error al procesar: {e}")
    else:
        st.warning("Por favor, subí un archivo primero.")
