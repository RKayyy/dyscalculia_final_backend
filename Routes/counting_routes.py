import base64
import logging
import time
from fastapi.responses import StreamingResponse
import requests
from fastapi import APIRouter, HTTPException
from Config.database import user_registration_collection, user_profile_collection, quiz_collection, \
    predicted_values_collection, generated_questions_collection  # Updated collection names
import re
import google.generativeai as genai
import os
from Models.User_Profile import User_Profile
from bson.binary import Binary
from io import BytesIO
from PIL import Image

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Retrieve the keys
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
FLUX_API_KEY = os.getenv("FLUX_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

counting_router = APIRouter()

# Configure the generative AI model
genai.configure(api_key=GENAI_API_KEY)

question_types = {
    "counting": {
        "count_1" : 'Create a sentence like "Count the number of {object1} on/in the {object2}," focusing on objects recognizable and interesting to children aged 2-7, such as animals, toys, fruits, etc. Provide the response in this format object1:"object name", object2:"object name".'
    },
    "coloring": [],
    "calculation": []
}

@counting_router.post("/count_1")
def count_1(data:dict):
    uid = data.get("uid")
    image_generation({"uid":uid})
    return {
        "question_image":"",
        "question_string": "",
        "options":[],
        "correct_answer":""
    }

@counting_router.post("/prompt_generation")
def prompt_generation():
    # Select the prompt based on the type
    prompt_selector = question_types["counting"]["count_1"]
    # Initialize the model and generate content
    model = genai.GenerativeModel("gemini-1.5-pro")
    response = model.generate_content(prompt_selector)

    # Parse the response to extract object1 and object2
    generated_text = response.text
    print(generated_text)
    # Try to extract object1 and object2 based on the response format
    match = re.search(r'object1:\s*"([^"]+)"\s*,?\s*object2:\s*"([^"]+)"', generated_text.replace("\n", " "))
    print(match)
    if match:
        object1 = match.group(1)
        object2 = match.group(2)
    else:
        object1,object2 = None, None

        # Return response with extracted objects and the original generated text
    return {
        "generated_text": generated_text.split("\n")[0],
        "object1": object1,
        "object2": object2
    }

# IMAGE GENERATION
@counting_router.post("/flux_image")
def image_generation(data: dict):
    uid = data.get("uid")
    response = prompt_generation()
    prompt = response["generated_text"]
    object1 = response["object1"]
    object2 = response["object2"]

    bfl_request = requests.post(
        'https://api.bfl.ml/v1/flux-pro-1.1',
        headers={
            'accept': 'application/json',
            'x-key': FLUX_API_KEY,
            'Content-Type': 'application/json',
        },
        json={
            'prompt': f"Make an image with 5-15 of {response['object1']} positioned on a {response['object2']} in a kid-friendly style with bright colors and clear shapes.",
            'width': 1024,
            'height': 768,
        },
    ).json()

    request_id = bfl_request.get("id")
    print(request_id)
    image_url = None
    generated_images = {}
    image_count = 1

    while request_id:
        time.sleep(0.5)
        result = requests.get(
            'https://api.bfl.ml/v1/get_result',
            headers={
                'accept': 'application/json',
                'x-key': "81137eb1-5aad-40ce-8e2f-3c86a1fc39a4",
            },
            params={
                'id': request_id,
            },
        ).json()

        if result["status"] == "Ready":
            image_url = result["result"]["sample"]
            print(f"Image URL: {image_url}")

            # Download the image content from the URL
            image_response = requests.get(
                image_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                }
            )

            if image_response.status_code == 200:
                with open(f"generated_image_{image_count}.jpeg", "wb") as img_file:
                    img_file.write(image_response.content)
                image_bytes = BytesIO(image_response.content).getvalue()

                # Store each image with a string key and index
                generated_images[str(image_count)] = {
                    "index": image_count,  # Adding index
                    "prompt": prompt,
                    "image": Binary(image_bytes)
                }

                image_count += 1  # Increment the image count for the next image
            else:
                print(f"Failed to download the image, status code: {image_response.status_code}")

            # Check if you want to stop after one image, or loop through multiple requests
            break
        else:
            print(f"Status: {result['status']}")

    # Save the generated images to the database
    if generated_images:
        # Fetch the current document (if exists) to append new images to the array
        existing_document = generated_questions_collection.find_one({"uid": uid})

        updated_images = []
        for img_key, img_data in generated_images.items():
            updated_images.append(img_data)  # Add each generated image with index

        if existing_document:
            # Append to existing images
            existing_generated_images = existing_document.get("generated_images", [])
            updated_images = existing_generated_images + updated_images
        else:
            # If the document doesn't exist, initialize with the new images
            updated_images = updated_images

        # Update or insert the new array of images
        generated_questions_collection.update_one(
            {"uid": uid},  # Match by uid
            {
                "$set": {"generated_images": updated_images}  # Set the full array of images (overwrite if exists)
            },
            upsert=True  # If no document is found with the uid, insert a new one
        )

        # Handle the uploaded file and generate content as before
        uploaded_file = genai.upload_file(f"generated_image_{image_count - 1}.jpeg")
        print(f"{uploaded_file=}")

        model = genai.GenerativeModel("gemini-1.5-flash")
        result = model.generate_content(
            [uploaded_file, "\n\n",
             f"Count the {response['object1']} in/on {response['object2']} and give the response in the format number_of_object='number' "]
        )

        return {
            "result": result.text,
            "object1": object1,
            "object2": object2,
            "question_string": f"Count the {object1} in/on {object2} and give the response in the format number_of_object='number'",
            "image_url": image_url
        }
    else:
        print("No images were generated.")


# GET IMAGE FROM MONGODB
@counting_router.post("/get_image")
def get_image(data: dict):
    # Validate that UID is provided
    uid = data.get("uid")
    if not uid:
        raise HTTPException(status_code=400, detail="UID is required")

    # Fetch the document from the collection using the provided UID
    image_data = generated_questions_collection.find_one({"uid": uid})
    if not image_data:
        raise HTTPException(status_code=404, detail="UID not found")

    # Extract the last image from the generated_images array
    generated_images = image_data.get("generated_images", [])
    if not generated_images:
        raise HTTPException(status_code=404, detail="No images found for this UID")

    # Get the last image entry (most recent)
    last_image_entry = generated_images[-1]
    if not last_image_entry or "image" not in last_image_entry:
        raise HTTPException(status_code=404, detail="No image data found for this UID")

    # Retrieve the image data (binary or base64)
    image_data = last_image_entry["image"]
    print(image_data)
    decoded_image = BytesIO(image_data)

    # Process the image
    try:
        image = Image.open(decoded_image)  # Open the image using PIL
        img_io = BytesIO()
        image.save(img_io, "JPEG")
        img_io.seek(0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")

    # Send the image file as a streaming response
    return StreamingResponse(img_io, media_type="image/jpeg")
