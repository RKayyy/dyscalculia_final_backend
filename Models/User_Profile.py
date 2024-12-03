from typing import Dict
from pydantic import BaseModel
from enum import Enum

# Define an Enum for Gender options
class Gender(str, Enum):
    male = "Male"
    female = "Female"
    not_stated = "Other"

class User_Profile(BaseModel):
    uid: str
    child_name: str
    child_age: int
    child_gender: Gender
    parent_name: str
    parent_contact: int
    address: str
    preferred_subject: str
