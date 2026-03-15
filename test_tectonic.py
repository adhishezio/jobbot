import os
import subprocess

# 1. This simulates the EXACT data n8n and Gemini will output
n8n_mock_data = {
    "<<TO_COMPANY>>": "BMW Group",
    "<<TO_DEPARTMENT>>": "Personalabteilung",
    "<<TO_STREET>>": "Petuelring 130",
    "<<TO_PLZ_CITY>>": "80809 München",
    "<<DATE>>": "25. Februar 2026",
    "<<POSITION>>": "Computer Vision Engineer (m/w/d)",
    "<<PARA_ONE>>": "mit großem Interesse habe ich Ihre Stellenausschreibung für die Position als Computer Vision Engineer gelesen. Die Möglichkeit, bei der BMW Group an innovativen Lösungen für das autonome Fahren zu arbeiten, begeistert mich sehr.",
    "<<PARA_TWO>>": "Während meiner Tätigkeit als Data Scientist bei Knorr-Bremse habe ich tiefgehende Erfahrungen in der Entwicklung von Deep-Learning-Modellen, insbesondere mit PyTorch und YOLO, gesammelt. Die Optimierung von Modellen für den produktiven Einsatz und die Arbeit mit Docker gehören zu meinen Kernkompetenzen.",
    "<<PARA_THREE>>": "Gerne überzeuge ich Sie in einem persönlichen Gespräch von meiner Motivation und meinen technischen Fähigkeiten. Ich freue mich sehr auf Ihre Rückmeldung.",
}

def simulate_n8n_to_pdf():
    print("📝 Reading your strict LaTeX template...")
    with open("cover_letter_template.tex", "r", encoding="utf-8") as f:
        tex_content = f.read()

    print("💉 Injecting simulated n8n variables...")
    for tag, value in n8n_mock_data.items():
        tex_content = tex_content.replace(tag, value)

    # CRITICAL: Fix the signature path for LOCAL Windows testing.
    # Your template uses the Docker path (/app/assets/signature.png). 
    # We temporarily swap it to look in the current folder just for this test.
    tex_content = tex_content.replace("/app/assets/signature.png", "signature.png")

    # Save the injected file
    temp_file = "final_output.tex"
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(tex_content)

    print("⚙️ Compiling PDF...")
    
    # Try to compile using Tectonic if you have it installed, otherwise fallback to standard pdflatex for the test
    try:
        # Tectonic command
        subprocess.run([".\\tectonic.exe", temp_file], check=True)
        print("✅ Success! Compiled using Tectonic.")
    except FileNotFoundError:
        print("⚠️ Tectonic not found locally. Falling back to pdflatex...")
        try:
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", temp_file],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print("✅ Success! Compiled using standard pdflatex.")
        except Exception as e:
            print(f"❌ Compilation failed: {e}")

simulate_n8n_to_pdf()