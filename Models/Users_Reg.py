from typing import Dict
from pydantic import BaseModel

class Users_Reg(BaseModel):
    uid: str
    username: str
    email: str
    password: str
    confirm_password: str
