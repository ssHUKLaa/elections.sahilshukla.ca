from flask import Flask, redirect, render_template_string

# Initialize Flask app
server = Flask(__name__)

# Main route with button to redirect
@server.route('/')
def home():
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>US 2024 Dashboard</title>
        <style>
            :root {
                --primary-color: #3a86ff;
                --secondary-color: #ff006e;
                --background-color: #f8f9fa;
                --text-color: #212529;
            }
            
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: var(--background-color);
                color: var(--text-color);
                line-height: 1.6;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                padding: 20px;
            }
            
            .container {
                max-width: 800px;
                width: 100%;
                background-color: white;
                border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                padding: 40px;
                text-align: center;
            }
            
            h1 {
                font-size: 2.5rem;
                margin-bottom: 20px;
                color: var(--primary-color);
                position: relative;
                display: inline-block;
            }
            
            h1::after {
                content: '';
                position: absolute;
                bottom: -10px;
                left: 50%;
                transform: translateX(-50%);
                width: 50px;
                height: 3px;
                background-color: var(--secondary-color);
            }
            
            p {
                margin-bottom: 30px;
                font-size: 1.1rem;
                color: #6c757d;
            }
            
            .btn {
                display: inline-block;
                background-color: var(--primary-color);
                color: white;
                padding: 12px 30px;
                border-radius: 50px;
                text-decoration: none;
                font-weight: 600;
                font-size: 1.1rem;
                border: none;
                cursor: pointer;
                transition: all 0.3s ease;
                box-shadow: 0 4px 6px rgba(58, 134, 255, 0.3);
            }
            
            .btn:hover {
                background-color: #2563eb;
                transform: translateY(-2px);
                box-shadow: 0 6px 8px rgba(58, 134, 255, 0.4);
            }
            
            .btn:active {
                transform: translateY(0);
            }
            
            .status {
                margin-top: 30px;
                font-size: 0.9rem;
                color: #6c757d;
            }
            
            .usa-flag {
                margin-bottom: 20px;
                font-size: 3rem;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="usa-flag">🇺🇸</div>
            <h1>US 2024 Dashboard</h1>
            <p>Access comprehensive data and analytics for the 2024 US elections. Click below to explore the dashboard.</p>
            <form action="/redirect-to-dash" method="get">
                <button type="submit" class="btn">View Dashboard</button>
            </form>
            <div class="status">Status: Work in Progress</div>
        </div>
    </body>
    </html>
    ''')

# Redirect to Dash app at /old/us2024 when the button is clicked
@server.route('/redirect-to-dash')
def redirect_to_dash():
    return redirect('/old/us2024')

