# ANPR
ANPR

This application provides simple automatic license plate recognition with a web
dashboard. The OCR pipeline is tuned for Polish license plates.

### Requirements

```
pip install -r requirements.txt
```

The system relies on EasyOCR and pytesseract. Ensure that the Tesseract binary
is installed on the host system.

### Improvements

The detection script now preprocesses plate images using noise reduction and
binary thresholding. When EasyOCR fails to read a number, the system falls back
to pytesseract with a whitelist of valid characters.
