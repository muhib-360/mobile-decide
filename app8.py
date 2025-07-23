from flask import Flask, render_template, request, jsonify, make_response
import pandas as pd
import os
import spacy
import re

app = Flask(__name__)

# Load dataset and clean numeric columns
DATASET_PATH = 'C:\\Users\\muhib\\Desktop\\python cleaning\\mobiledecide\\dataset\\antutu_priceoye_merged.csv'
try:
    df = pd.read_csv(DATASET_PATH)
    # Print columns for debugging
    print(f"Dataset columns: {list(df.columns)}")
    print(f"Loaded dataset with {len(df)} rows")
    # Convert price column to numeric
    price_column = 'Price_PKR'  # Confirmed column name
    if price_column in df.columns:
        df[price_column] = df[price_column].replace(r'[^\d.]', '', regex=True).astype(float)
    else:
        raise KeyError(f"Price column '{price_column}' not found in dataset. Available columns: {list(df.columns)}")
    # Ensure benchmark columns are numeric, allowing NaN for unmatched phones
    numeric_columns = ['Total Score', 'GPU Score', 'CPU Score', 'UX Score', 'Rating']
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
except FileNotFoundError:
    print(f"Dataset not found at {DATASET_PATH}")
    df = pd.DataFrame()

# Load spaCy model
nlp = spacy.load('en_core_web_sm')

def parse_query(query, brand=None):
    """Parse user query to extract budget and use case using spaCy and rules."""
    doc = nlp(query.lower())
    
    # Extract budget (e.g., "90k", "90000 rupees")
    budget = None
    for ent in doc.ents:
        if ent.label_ == 'MONEY':
            text = ent.text.replace('rupees', '').replace('pkr', '').strip()
            print(f"NER extracted: {text}")  # Debug NER output
            match = re.search(r'(\d+\.?\d*)(k| thousand)?', text, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                budget = int(value * 1000 if match.group(2) in ['k', ' thousand'] else value)
    
    # Fallback: Directly search query for budget if NER fails
    if budget is None:
        match = re.search(r'(\d+\.?\d*)(k| thousand)', query.lower())
        if match:
            value = float(match.group(1))
            budget = int(value * 1000)
            print(f"Fallback extracted: {match.group(0)} -> {budget}")  # Debug fallback
    
    # Extract use case with expanded keywords
    use_case = 'balanced'
    everyday_keywords = ['everyday', 'daily', 'normal', 'regular', 'basic', 'standard', 'usual', 'casual', 'tasks', 'use']
    if any(word in query.lower() for word in ['performance', 'gaming']):
        use_case = 'performance'
        print(f"Use case matched: performance (keywords: performance, gaming)")
    elif any(word in query.lower() for word in everyday_keywords):
        use_case = 'everyday'
        matched_words = [word for word in everyday_keywords if word in query.lower()]
        print(f"Use case matched: everyday (keywords: {', '.join(matched_words)})")
    
    print(f"Parsed query: {query} -> Budget: {budget or 50000}, Use Case: {use_case}, Brand: {brand}")
    return {'budget': budget or 50000, 'use_case': use_case, 'brand': brand}

def get_recommendations(budget, use_case, brand=None):
    """Generate phone recommendations based on budget, use case, and optional brand."""
    price_column = 'Price_PKR'  # Confirmed column name
    # Filter phones within budget
    matched_df = df[(df[price_column] <= budget) & (df['Total Score'].notna())].copy()
    unmatched_df = df[(df[price_column] <= budget) & (df['Total Score'].isna())].copy()

    # Apply brand filter if provided
    if brand and brand.lower() in df['Brand'].str.lower().values:
        matched_df = matched_df[matched_df['Brand'].str.lower() == brand.lower()]
        unmatched_df = unmatched_df[unmatched_df['Brand'].str.lower() == brand.lower()]

    # Rank matched phones
    if use_case == 'performance':
        matched_df.loc[:, 'Score'] = 0.6 * matched_df['GPU Score'] + 0.4 * matched_df['CPU Score']
        ranked_df = matched_df.sort_values(by='Score', ascending=False)
    elif use_case == 'everyday':
        ranked_df = matched_df.sort_values(by='UX Score', ascending=False)
    else:  # balanced
        ranked_df = matched_df.sort_values(by='Total Score', ascending=False)

    # Get top 3 matched phones
    recommendations = ranked_df[['Brand', 'Model', price_column, 'Total Score', 'Rating', 'URL']].head(3).to_dict('records')

    # Add unmatched phones as fallback if fewer than 3 matched
    if len(recommendations) < 3 and brand:
        fallback_df = unmatched_df.sort_values(by='Rating', ascending=False)
        for _, row in fallback_df.head(3 - len(recommendations)).iterrows():
            recommendations.append({
                'Brand': row['Brand'],
                'Model': row['Model'],
                'Price_PKR': row[price_column],
                'Total Score': None,
                'Rating': row['Rating'],
                'URL': row['URL'],
                'Note': 'Benchmark scores unavailable'
            })

    # Generate message
    message = f"Here are the top {brand or 'phones'} under PKR {budget:,}"
    if use_case == 'performance':
        message += " for performance and gaming"
    elif use_case == 'everyday':
        message += " for everyday use"
    message += ":"

    print(f"Recommendations: {len(recommendations)} phones returned")
    return {'message': message, 'recommendations': recommendations}

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/recommend', methods=['POST'])
def recommend():
    user_input = request.json.get('message', '')
    brand = request.json.get('brand', '')
    if not user_input and not brand:
        return jsonify({'error': 'No input or brand provided'}), 400
    parsed = parse_query(user_input, brand)
    response = get_recommendations(parsed['budget'], parsed['use_case'], parsed['brand'])
    resp = make_response(jsonify(response))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

if __name__ == '__main__':
    app.run(debug=True)