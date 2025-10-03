#!/bin/bash

# Start both Streamlit GUI and FastAPI server

# Start Streamlit in the background
echo "Starting Streamlit GUI on port 8501..."
streamlit run src/pdf_ocr_compress/gui/basic.py &
STREAMLIT_PID=$!

# Start FastAPI server in the background
echo "Starting FastAPI server on port 8502..."
python -m uvicorn pdf_ocr_compress.api.server:app --host 0.0.0.0 --port 8502 &
API_PID=$!

# Function to handle shutdown
shutdown() {
    echo "Shutting down services..."
    kill $STREAMLIT_PID $API_PID 2>/dev/null
    exit 0
}

# Trap SIGTERM and SIGINT
trap shutdown SIGTERM SIGINT

echo "Services started:"
echo "  - Streamlit GUI: http://localhost:8501"
echo "  - REST API: http://localhost:8502"
echo "  - API Docs: http://localhost:8502/docs"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for both processes
wait
