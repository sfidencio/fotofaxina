"""Descrições usadas pela IA (CLIP) para cada categoria.

Ficam num módulo sem dependências porque são usadas em dois lugares:
- packaging/build_model.py, que transforma estas frases em vetores no build;
- app/classifier.py, que só compara a imagem com esses vetores já prontos.
Mudou alguma frase? Gere o modelo de novo (o build do GitHub faz isso sozinho).
Frases em inglês funcionam melhor com o CLIP.
"""

MODEL_ID = "openai/clip-vit-base-patch32"
IMAGE_SIZE = 224
MEAN = (0.48145466, 0.4578275, 0.40821073)
STD = (0.26862954, 0.26130258, 0.27577711)

PROMPTS: dict[str, list[str]] = {
    "foto": [
        "a photo of people", "a family photo", "a selfie", "a photo of a child",
        "a photo of friends at a party", "a photo of a pet", "a photo of a birthday celebration",
        "a photo of food on a table",
    ],
    "paisagem": [
        "a landscape photo", "a travel photo of a city", "a photo of nature",
        "a photo of a beach", "a photo of a building", "a photo of the sky at sunset",
    ],
    "meme": [
        "an internet meme", "a meme with a text caption", "a cartoon or comic strip",
        "an image with a motivational quote", "a funny picture with text on it",
        "a sticker with a cartoon character", "a good morning message image with flowers and text",
    ],
    "print": [
        "a screenshot of a phone", "a screenshot of a chat conversation",
        "a screenshot of a website", "a screenshot of a computer screen",
        "a screenshot of a social media post",
    ],
    "documento": [
        "a photo of a document", "a photo of a receipt", "a scanned paper document",
        "a photo of an ID card", "a photo of a whiteboard", "a photo of a bill or invoice",
    ],
}
