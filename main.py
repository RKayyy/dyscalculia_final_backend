from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from Routes.counting_routes import counting_router
from Routes.routes import router
from pymongo.mongo_client import MongoClient

# Initialize FastAPI app
app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(router)
app.include_router(counting_router)


