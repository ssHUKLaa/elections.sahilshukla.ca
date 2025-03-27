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
        <title>Sahil Shukla's Election Predictions</title>
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
            <div class="usa-flag">Canadian Elections</div>
            <h1>Canadian Federal 2025</h1>
            <p>Analytics for the Canadian Federal election, which is set to take place in 2025.</p>
            <form action="/redirect-to-can2025" method="get">
                <button type="submit" class="btn">View Prediction</button>
            </form>
            <div class="status">Status: WIP</div>
        </div>                        
        <div class="container">
            <div class="usa-flag">US Elections</div>
            <h1>US General 2024</h1>
            <p>My prediction for the United States general election which took place in 2024.</p>
            <form action="/redirect-to-dash" method="get">
                <button type="submit" class="btn">View Prediction</button>
            </form>
            <div class="status">Status: Finished</div>
        </div>
    </body>
    </html>
    ''')

@server.route('/redirect-to-can2025')
def redirect_to_can2025():
    return redirect('/can2025')

@server.route('/redirect-to-us2024')
def redirect_to_us2024():
    return redirect('/old/us2024')

