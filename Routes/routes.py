import base64
import logging

import mimetypes

import pickle
import random
import time
from io import BytesIO
from fastapi.responses import StreamingResponse
from PIL import Image
from bson import Binary

import numpy as np
import requests
from skfuzzy import control as ctrl
from fastapi import APIRouter, HTTPException
from Config.database import user_registration_collection, user_profile_collection, quiz_collection, \
    predicted_values_collection  # Updated collection names

from Config.database import user_registration_collection, user_profile_collection, quiz_collection, \
    predicted_values_collection, generated_questions_collection  # Updated collection names

from bson import ObjectId
import re
import uuid
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import google.generativeai as genai
import os

from Models.User_Profile import User_Profile
from bson.binary import Binary
from io import BytesIO
from PIL import Image

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

# Retrieve the keys
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
FLUX_API_KEY = os.getenv("FLUX_API_KEY")
router = APIRouter()

email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
password_regex = r'^(?=.[a-z])(?=.[A-Z])(?=.\d)(?=.[@$!%?&])[A-Za-z\d@$!%?&]{8,}$'


# REGISTER endpoint
@router.post("/register")
async def post_user(user: dict):
    # Validate email format
    if not re.match(email_regex, user.get('email', '')):
        logger.error(f"Invalid email format for email: {user.get('email')}")
        raise HTTPException(status_code=400, detail="Invalid email format.")

    # Validate password complexity
    if not re.match(password_regex, user.get('password', '')):
        logger.error(f"Password does not meet complexity requirements for user: {user.get('email')}")

        raise HTTPException(status_code=400,
                            detail="Password does not meet complexity requirements. It must contain at least 8 characters, one uppercase letter, one lowercase letter, one number, and one special symbol.")

    # Check if passwords match
    if user.get('password') != user.get('confirm_password'):
        logger.error(f"Passwords do not match for user: {user.get('email')}")
        raise HTTPException(status_code=400, detail="Passwords do not match.")

    # Check if the email is already in the database
    existing_user = user_registration_collection.find_one({"email": user.get("email")})
    if existing_user:
        logger.error(f"Email already exists for email: {user.get('email')}")
        raise HTTPException(status_code=400, detail="Email already exists. Please use a different email.")

    # Generate a unique UID
    uid = str(uuid.uuid4())

    # Construct user data
    user_data = {
        "uid": uid,
        "username": user.get('username'),
        "email": user.get('email'),
        "password": user.get('password'),
        "confirm_password": user.get('confirm_password')
    }

    # Insert the user data into the collection
    user_registration_collection.insert_one(user_data)

    logger.info(f"User successfully registered with UID: {uid}")


# LOGIN
@router.post("/login")
async def login_user(user: dict):
    username = user.get("username")
    password = user.get("password")

    if not password:
        raise HTTPException(status_code=400, detail="Password is required.")

    db_user = user_registration_collection.find_one({"email": username}) or user_registration_collection.find_one(
        {"username": username})
    if db_user and db_user["password"] == password:
        return {"message": "Login successful!", "uid": db_user["uid"]}
    else:
        raise HTTPException(status_code=400, detail="Invalid email or password.")


# PROFILE
@router.post("/profile")
async def post_user_details(user: dict):
    # Find user by email in the UserRegistrations collection
    existing_user = user_registration_collection.find_one({"uid": user.get("uid")})

    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found. Please register first.")

    # Get the UID of the registered user
    uid = existing_user.get("uid")

    # Construct the profile data with the retrieved UID
    profile_data = {
        "uid": uid,
        "child_name": user.get("child_name"),
        "child_age": user.get("child_age"),
        "child_gender": user.get("child_gender"),
        "parent_name": user.get("parent_name"),
        "parent_contact": user.get("parent_contact"),
        "address": user.get("address"),
        "preferred_subject": user.get("preferred_subject")
    }

    # Insert the profile data into the profile collection
    user_profile_collection.insert_one(profile_data)

    return {"message": "User profile created successfully!", "uid": uid}


# SCORES
@router.post("/score")
async def post_user_score(data: dict):
    uid = data.get("uid")
    quiz_id = str(data.get("quiz_id"))

    if not uid or not quiz_id:
        raise HTTPException(status_code=400, detail="Missing 'uid' or 'quiz_id'.")

    existing_user = quiz_collection.find_one({"uid": uid})

    if not existing_user:
        new_quiz_data = {
            "uid": uid,
            "quizzes": {
                quiz_id: {
                    "1": {
                        "question1_id": data.get("question1_id"),
                        "question2_id": data.get("question2_id"),
                        "question3_id": data.get("question3_id"),
                        "question4_id": data.get("question4_id"),
                        "question5_id": data.get("question5_id"),
                        "average_result": data.get("average_result")
                    }
                }
            }
        }
        quiz_collection.insert_one(new_quiz_data)
        return {"message": "First attempt for this quiz recorded!", "attempt_number": 1}

    quizzes = existing_user.get("quizzes", {})
    current_quiz = quizzes.get(quiz_id, {})

    attempt_number = len(current_quiz) + 1

    current_quiz[str(attempt_number)] = {
        "question1_id": data.get("question1_id"),
        "question2_id": data.get("question2_id"),
        "question3_id": data.get("question3_id"),
        "question4_id": data.get("question4_id"),
        "question5_id": data.get("question5_id"),
        "average_result": data.get("average_result")
    }

    quizzes[quiz_id] = current_quiz

    quiz_collection.update_one(
        {"uid": uid},
        {"$set": {"quizzes": quizzes}}
    )

    return {"message": f"Attempt {attempt_number} for quiz {quiz_id} recorded!", "attempt_number": attempt_number}


# AVERAGE SCORES : new api to post score without question ids
@router.post("/average_score")
async def post_user_average_score(data: dict):
    uid = data.get("uid")
    quiz_id = str(data.get("quiz_id"))
    quiz_type = data.get("quiz_type")  # e.g., "counting", "coloring", etc.
    average_score = data.get("average_score")

    if not uid or not quiz_id or not quiz_type or average_score is None:
        raise HTTPException(status_code=400, detail="Missing required fields.")

    existing_user = quiz_collection.find_one({"uid": uid})

    if not existing_user:
        # If user doesn't exist, create a new entry
        new_data = {
            "uid": uid,
            "quizzes": {
                quiz_id: {
                    quiz_type: [average_score]
                }
            }
        }
        quiz_collection.insert_one(new_data)
        return {"message": f"First average score recorded for {quiz_type} in quiz {quiz_id}!"}

    quizzes = existing_user.get("quizzes", {})
    current_quiz = quizzes.get(quiz_id, {})

    if quiz_type not in current_quiz:
        current_quiz[quiz_type] = []

    # Append the new average score
    current_quiz[quiz_type].append(average_score)

    # Update the database
    quizzes[quiz_id] = current_quiz
    quiz_collection.update_one(
        {"uid": uid},
        {"$set": {"quizzes": quizzes}}
    )

    return {"message": f"Average score for {quiz_type} in quiz {quiz_id} recorded successfully!"}


# PREDICTION
with open('fuzzy_model.pkl', 'rb') as f:
    fuzzy_ctrl = pickle.load(f)

# Ensure that the loaded model is a ControlSystem
if not isinstance(fuzzy_ctrl, ctrl.ControlSystem):
    raise ValueError("Loaded object is not a valid ControlSystem instance.")


def apply_fuzzy_logic(counting_input, color_input, calculation_input, fuzzy_ctrl):
    simulator = ctrl.ControlSystemSimulation(fuzzy_ctrl)
    simulator.input['Counting_Ability'] = np.mean(counting_input)
    simulator.input['Color_Ability'] = np.mean(color_input)
    simulator.input['Calculation_Ability'] = np.mean(calculation_input)
    simulator.compute()

    output_percentage = simulator.output.get('Percentage', None)
    return output_percentage


# PREDICT DYSCALCULIA
@router.post("/predict")
async def predict_dyscalculia(data: dict):
    uid = data.get("uid")

    if not uid:
        raise HTTPException(status_code=400, detail="Missing 'uid'.")

    # Fetch the user data from the quiz collection
    existing_user = quiz_collection.find_one({"uid": uid})

    if not existing_user:
        return {"message": "User not found", "result": 0}

    # Check if quizzes 1, 2, and 3 have data
    quizzes = existing_user.get("quizzes", {})

    missing_quizzes = []
    if "1" not in quizzes or not quizzes["1"]:
        missing_quizzes.append("Quiz 1")
    if "2" not in quizzes or not quizzes["2"]:
        missing_quizzes.append("Quiz 2")
    if "3" not in quizzes or not quizzes["3"]:
        missing_quizzes.append("Quiz 3")

    if missing_quizzes:
        return {"message": "Please attempt the following quizzes:", "quizzes_to_attempt": missing_quizzes}

    # Get the last attempt for quiz 1, 2, and 3
    last_attempt_1 = quizzes["1"][str(len(quizzes["1"]))]
    last_attempt_2 = quizzes["2"][str(len(quizzes["2"]))]
    last_attempt_3 = quizzes["3"][str(len(quizzes["3"]))]

    # Extract the relevant inputs from the last attempts
    counting_input = [(last_attempt_1["average_result"] / 100)]
    color_input = [(last_attempt_2["average_result"] / 100)]
    calculation_input = [(last_attempt_3["average_result"] / 100)]

    # Apply the fuzzy logic to predict the percentage
    prediction_result = apply_fuzzy_logic(counting_input, color_input, calculation_input, fuzzy_ctrl)
    existing_prediction = predicted_values_collection.find_one({"uid": uid})

    if existing_prediction:
        # Safely append the new prediction to the existing dictionary
        predicted_values = existing_prediction["predicted_values"]
        next_index = str(len(predicted_values) + 1)  # Increment safely
        predicted_values[next_index] = prediction_result

        predicted_values_collection.update_one(
            {"uid": uid},
            {"$set": {"predicted_values": predicted_values}}
        )
    else:
        # Create a new dictionary entry for a new UID
        new_prediction_data = {
            "uid": uid,
            "predicted_values": {
                "1": prediction_result  # Start with the first prediction
            }
        }
        predicted_values_collection.insert_one(new_prediction_data)

    return {"message": "Prediction successful", "result": prediction_result}


# PREDICTION GRAPH
@router.post("/prediction_tables")
async def get_prediction_data(data: dict):
    # Fetch the prediction data from the predicted_values_collection based on uid
    prediction_data = predicted_values_collection.find_one({"uid": data.get("uid")})

    # Check if the uid exists in the collection
    if not prediction_data:
        raise HTTPException(status_code=404, detail="No predictions found for the given uid.")

    # Return the predicted values
    return {
        "uid": data.get("uid"),
        "predicted_values": prediction_data.get("predicted_values", {})
    }


@router.post("/user_details")
async def get_user_details(data: dict):
    user_profile = user_profile_collection.find_one({"uid": data.get("uid")})

    # Log the result from the database query
    if user_profile:
        print(f"User profile found: {user_profile}")
    else:
        print("User profile not found in the database.")

    # Check if the user exists in the collection
    if not user_profile:
        raise HTTPException(status_code=404, detail="User profile not found.")

    # Convert _id to string to avoid BSON issues
    user_profile['_id'] = str(user_profile['_id'])  # Convert ObjectId to string

    # Map MongoDB result to Pydantic model fields
    user_profile_data = User_Profile(
        uid=user_profile['uid'],
        child_name=user_profile['child_name'],
        child_age=user_profile['child_age'],
        child_gender=user_profile['child_gender'],
        parent_name=user_profile['parent_name'],
        parent_contact=user_profile['parent_contact'],
        address=user_profile['address'],
        preferred_subject=user_profile['preferred_subject']
    )

    return user_profile


# RESULT HISTORY

@router.post("/result_history")
async def get_result_history(data: dict):
    # Fetch the user's quiz data from the quiz_collection
    existing_user = quiz_collection.find_one({"uid": data.get("uid")})

    # Check if the user exists and has quiz data
    if not existing_user or 'quizzes' not in existing_user:
        raise HTTPException(status_code=404, detail="User quiz data not found.")

    quizzes = existing_user.get("quizzes", {})

    # Initialize lists to store average results for counting, coloring, and calculation quizzes
    counting_results = []
    coloring_results = []
    calculation_results = []

    # Check and extract results for each quiz (1, 2, 3 representing counting, coloring, calculation)
    if "1" in quizzes:  # Quiz 1: Counting
        for attempt_num, attempt_data in quizzes["1"].items():
            counting_results.append(attempt_data["average_result"])

    if "2" in quizzes:  # Quiz 2: Coloring
        for attempt_num, attempt_data in quizzes["2"].items():
            coloring_results.append(attempt_data["average_result"])

    if "3" in quizzes:  # Quiz 3: Calculation
        for attempt_num, attempt_data in quizzes["3"].items():
            calculation_results.append(attempt_data["average_result"])

    # Return the results as three lists

    results = {
        "counting_results": counting_results,
        "coloring_results": coloring_results,
        "calculation_results": calculation_results
    }

    return results

