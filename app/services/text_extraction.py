import io
import logging
from typing import List, Optional
from dataclasses import dataclass
from PIL import Image, ImageOps
import pymupdf
import pytesseract

logger = logging.getLogger(__name__)


@dataclass
class PageExtractionResult:
    page_number: int
    raw_text: str
    extraction_method: str # 'native_text' | 'ocr_tesseract' | 'failed'
    confidence: float
    error_message: Optional[str] = None


def _calculate_ocr_confidence(pil_img: Image.Image) -> float:
    """Calculate mean word-level confidence score from Tesseract OCR (0.0 - 1.0)."""
    try:
        data = pytesseract.image_to_data(pil_img, output_type=pytesseract.Output.DICT)
        conf_list = [int(c) for c in data.get("conf", []) if str(c) != "-1" and int(c) >= 0]
        if conf_list:
            avg_conf = sum(conf_list) / len(conf_list)
            # Normalize to 0.0 - 1.0 range, bounded
            return round(max(0.05, min(0.95, avg_conf / 100.0)), 2)
        return 0.50
    except Exception as e:
        logger.warning("Failed to compute OCR word confidence: %s", e)
        return 0.50


def extract_document_pages(storage_path: str, file_type: str) -> List[PageExtractionResult]:
    """
    Stage 2 Text Extraction Pipeline per PRD §4.
    - PDF fast-path: Detects selectable text layer via PyMuPDF.
    - OCR fallback: Runs Tesseract OCR on scanned PDF pages and images (JPG/PNG).
    - Failure isolation: Failures on individual pages are caught and recorded per-unit.
    """
    results: List[PageExtractionResult] = []

    if file_type == "pdf":
        try:
            doc = pymupdf.open(storage_path)
            total_pages = len(doc)
            logger.info("[EXTRACTOR] Processing PDF with %d page(s): %s", total_pages, storage_path)

            for page_idx in range(total_pages):
                page_number = page_idx + 1
                try:
                    page = doc[page_idx]
                    native_text = page.get_text("text").strip()

                    # Fault-injection check for testing failure isolation per PRD §12
                    if "[SIMULATED_PAGE_CORRUPTION]" in native_text:
                        raise RuntimeError(f"Corrupt rendering stream detected on page {page_number}")

                    alphanum_count = sum(c.isalnum() for c in native_text)

                    # Digital PDF fast path: selectable text layer present
                    if alphanum_count >= 15:
                        logger.info(
                            "[EXTRACTOR] Page %d: Digital text layer detected (%d chars). Fast path selected.",
                            page_number, len(native_text)
                        )
                        results.append(PageExtractionResult(
                            page_number=page_number,
                            raw_text=native_text,
                            extraction_method="native_text",
                            confidence=0.98
                        ))
                    else:
                        # Scanned PDF fallback path: render page to image and OCR
                        logger.info(
                            "[EXTRACTOR] Page %d: No selectable text layer. Falling back to Tesseract OCR.",
                            page_number
                        )
                        pix = page.get_pixmap(dpi=200)
                        img_bytes = pix.tobytes("png")
                        pil_img = Image.open(io.BytesIO(img_bytes))

                        # Auto-correct orientation if necessary
                        pil_img = ImageOps.exif_transpose(pil_img) or pil_img

                        ocr_text = pytesseract.image_to_string(pil_img).strip()
                        ocr_conf = _calculate_ocr_confidence(pil_img)

                        results.append(PageExtractionResult(
                            page_number=page_number,
                            raw_text=ocr_text,
                            extraction_method="ocr_tesseract",
                            confidence=ocr_conf
                        ))

                except Exception as page_err:
                    logger.error("[EXTRACTOR] Failure on page %d: %s", page_number, str(page_err), exc_info=True)
                    results.append(PageExtractionResult(
                        page_number=page_number,
                        raw_text="",
                        extraction_method="failed",
                        confidence=0.0,
                        error_message=f"Extraction failed on page {page_number}: {str(page_err)}"
                    ))

            doc.close()

        except Exception as doc_err:
            logger.error("[EXTRACTOR] Failed to open PDF document: %s", str(doc_err), exc_info=True)
            results.append(PageExtractionResult(
                page_number=1,
                raw_text="",
                extraction_method="failed",
                confidence=0.0,
                error_message=f"Failed to open PDF document: {str(doc_err)}"
            ))

    elif file_type in ["jpg", "jpeg", "png"]:
        page_number = 1
        try:
            logger.info("[EXTRACTOR] Processing image via Tesseract OCR: %s", storage_path)
            pil_img = Image.open(storage_path)
            pil_img = ImageOps.exif_transpose(pil_img) or pil_img

            ocr_text = pytesseract.image_to_string(pil_img).strip()
            ocr_conf = _calculate_ocr_confidence(pil_img)

            results.append(PageExtractionResult(
                page_number=page_number,
                raw_text=ocr_text,
                extraction_method="ocr_tesseract",
                confidence=ocr_conf
            ))
        except Exception as img_err:
            logger.error("[EXTRACTOR] Failed to OCR image %s: %s", storage_path, str(img_err), exc_info=True)
            results.append(PageExtractionResult(
                page_number=page_number,
                raw_text="",
                extraction_method="failed",
                confidence=0.0,
                error_message=f"Failed to extract text from image: {str(img_err)}"
            ))

    else:
        results.append(PageExtractionResult(
            page_number=1,
            raw_text="",
            extraction_method="failed",
            confidence=0.0,
            error_message=f"Unsupported file type: {file_type}"
        ))

    return results
