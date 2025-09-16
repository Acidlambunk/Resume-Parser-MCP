# Json to Json Resume-Parser MCP

This is a resume parser MCP that takes a random json input:
{
  "raw_text": "John Doe, Software Engineer with 3 years of experience in Python, AWS, Docker. Worked at Acme Inc from 2020 to 2023..."
}
Into a more sturctured output:
{
  "skills": ["Python", "AWS", "Docker"],
  "experience": [
    {"company": "Acme Inc", "role": "Software Engineer", "years": "2020-2023"}
  ],
  "education": [],
  "projects": []
}
using gemini model.

---
**Clone the repository:**
   ```bash
   git clone https://github.com/Acidlambunk/Resume-Parser-MCP.git
   cd test
   ```

2. **Install uv and setup venv**
    use google and install uv 
    setup venv with 
    ```bash
    python -m venv (name)
    source (name)/bin/activate
    ```
   

2. **Install dependencies:**
   ```bash
   uv pip install -r requirements.txt
   ```

3. **Set up environment variables:**
- create a new `.env` file and add your API keys and Supabase credentials:
    ```
    GEMINI_API_KEY=AIzaSyCLwVB7z5Ylj8tBpjwaa3htPzj-AcarSTY
    GEMINI_MODEL=gemini-2.0-flash
    ```

4. **Run the API locally:**
   ```bash
   uv run mcp dev main.py
   ```

---