from mistralai import Mistral
import os

api_key = "Arh3aIXsSMFRr881jL5OzDg0eBIWCRgn"

client = Mistral(api_key=api_key)

uploaded_pdf = client.files.upload(
    file={
        "file_name": "uploaded_file.pdf",
        "content": open("uploaded_file.pdf", "rb"),
    },
    purpose="ocr"
)  