from openai import AsyncOpenAI
import json
import uuid
import os 
from dotenv import load_dotenv
from datetime import date, timedelta

# This tells Python to look for the .env file and load it
load_dotenv()
# Initialize the client pointing to DeepSeek's API
# Make sure to set DEEPSEEK_API_KEY in your Render environment variables!
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your-deepseek-api-key-here")

client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY, 
    base_url="https://api.deepseek.com" # Overriding the base URL to DeepSeek
)

async def generate_deepseek_solution(question_text: str) -> dict:
    """
    Sends the user's question to DeepSeek and forces it to return 
    a highly structured JSON response matching our Flutter app's expectations.
    """
    
    system_prompt = """
    You are myLB AI, an expert academic tutor.
    Analyze the user's question and provide a clear, step-by-step solution.
    
    You MUST respond in valid JSON format exactly matching this structure:
    {
      "steps": [
        {
          "step_number": 1,
          "text": "Your detailed explanation for this step...",
          "highlight_terms": [
            {"term": "exact word to highlight", "color": "mint" | "peach"}
          ]
        }
      ],
      "confidence_score": 0.95
    }
    
    Rules for highlight_terms:
    - Use 'mint' for positive concepts, formulas, or correct answers.
    - Use 'peach' for warnings, common mistakes, or critical exceptions.
    - Do not highlight whole sentences, only key terms.
    """

    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Solve this: {question_text}"}
            ],
            response_format={"type": "json_object"} # Forces DeepSeek to output pure JSON
        )

        # Parse the JSON string returned by DeepSeek into a Python dictionary
        ai_data = json.loads(response.choices[0].message.content)
        
        # Add our backend-generated IDs and empty canvas links (we'll build Canvas linking later)
        ai_data["solution_id"] = f"sol_{uuid.uuid4().hex[:8]}"
        ai_data["canvas_links"] = [] 
        
        return ai_data

    except Exception as e:
        print(f"DeepSeek API Error: {e}")
        return None


# Add this below your existing generate_deepseek_solution function
async def generate_deepseek_study_plan(goal: str, target_date: date, days_remaining: int) -> dict:
    """
    Prompts DeepSeek to generate a structured 7-day study schedule.
    """
    # Calculate a starting date string (today) to help the AI format the week
    today_str = date.today().isoformat()
    
    system_prompt = f"""
    You are myLB AI, an expert academic planner. 
    The user wants to study for "{goal}". Their deadline is in {days_remaining} days ({target_date}).
    Today is {today_str}.
    
    Generate a highly realistic, balanced 7-day study plan starting from today.
    Include rest days to prevent burnout.
    
    You MUST respond in valid JSON format exactly matching this structure:
    {{
      "stats": {{
        "days_remaining": {days_remaining},
        "daily_target_mins": <calculate reasonable integer, e.g., 60>,
        "topics_count": <estimate number of topics to cover>
      }},
      "week": [
        {{
          "date": "YYYY-MM-DD",
          "day_label": "MON", 
          "has_session": true/false,
          "session_type": "study" | "review" | "rest"
        }} // Generate EXACTLY 7 items for the next 7 days
      ],
      "sessions": [
        {{
          "date": "YYYY-MM-DD",
          "time": "16:00",
          "subject": "Specific topic name",
          "duration_mins": <integer>,
          "mode": "flashcard" | "feynman" | "review",
          "priority": "normal" | "high" | "weak_area"
        }} // Generate ONLY the sessions for days where has_session is true
      ],
      "nudge": null 
    }}
    """

    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate my study plan."}
            ],
            response_format={"type": "json_object"} 
        )

        plan_data = json.loads(response.choices[0].message.content)
        return plan_data

    except Exception as e:
        print(f"DeepSeek API Error: {e}")
        return None