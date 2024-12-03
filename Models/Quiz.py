from typing import Dict
from pydantic import BaseModel

class QuizScore(BaseModel):
    question1_id: int
    question2_id: int
    question3_id: int
    question4_id: int
    question5_id: int
    average_result: int

class Quiz(BaseModel):
    uid: str
    quizzes: Dict[int, Dict[int, QuizScore]]
