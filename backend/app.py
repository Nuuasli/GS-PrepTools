"""
Hugging Face Spaces Entrypoint (Gradio SDK + FastAPI Integration)

This script mounts the FastAPI application onto a minimal Gradio interface,
allowing the Space to serve both the FastAPI endpoints (/api/v1/*, /docs)
and a status homepage.
"""

import os
import uvicorn
import gradio as gr
from main import app as fastapi_app

# Minimal UI for the Space homepage
with gr.Blocks(title="GS-Prep Backend API") as demo:
    gr.Markdown(
        """
        # 🚀 GS-Prep Backend API Service
        
        Backend API is active and ready to handle requests from the Vercel Frontend!
        
        * **API Documentation**: [/docs](/docs)
        * **Health Check Endpoint**: [/api/v1/health](/api/v1/health)
        """
    )

# Mount FastAPI app with Gradio on root
app = gr.mount_gradio_app(fastapi_app, demo, path="/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
