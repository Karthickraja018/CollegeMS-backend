"""
PDF Generator using xhtml2pdf.
"""
from xhtml2pdf import pisa
import logging

def generate_pdf(filepath: str, html_content: str) -> None:
    """
    Generate a styled PDF report from HTML using xhtml2pdf.

    Args:
        filepath: Where to save the PDF
        html_content: The fully rendered HTML string
    """
    with open(filepath, "w+b") as result_file:
        # Convert HTML to PDF
        pisa_status = pisa.CreatePDF(
            src=html_content,
            dest=result_file,
            encoding='UTF-8'
        )

    # Return True on success and False on errors
    if pisa_status.err:
        logging.error(f"Error generating PDF: {pisa_status.err}")
        raise Exception("Failed to generate PDF from HTML")
