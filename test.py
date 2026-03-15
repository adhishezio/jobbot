import google.generativeai as genai
import fitz  # PyMuPDF
import os

# 1. Use the exact same API key you are using in n8n!
genai.configure(api_key="")

def extract_and_structure_resume(pdf_path):
    print("📄 Reading PDF...")
    raw_text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            raw_text += page.get_text()

    print("🧠 Sending to Google Gemini for perfect structuring...")
    
    # We use Gemini 1.5 Flash - it is lightning fast and brilliant at text formatting
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = f"""
    You are an expert Data Extraction AI. 
    Format this raw resume into clean sections: Contact Info, Summary, Work Experience, Education, Skills.
    DO NOT summarize or remove any bullet points. Keep every single technical detail.
    Output ONLY the clean text.

    Raw PDF Text:
    {raw_text}
    """

    response = model.generate_content(prompt)
    
    # Save the perfect output for n8n to use
    with open("master_resume.txt", "w", encoding="utf-8") as f:
        f.write(response.text.strip())
        
    print("✅ Success! Flawless resume saved.")

# Run it
extract_and_structure_resume("Adhish_Resume_Data_Scientist_latex.pdf")
