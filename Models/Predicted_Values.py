from typing import Dict
from pydantic import BaseModel

class Predicted_Values(BaseModel):
    uid: str
    predicted_values: dict