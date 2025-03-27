from flask import Flask, redirect, render_template_string

# Initialize Flask app
server = Flask(__name__)

# Main route with button to redirect
@server.route('/')
def home():
    # Simple HTML with a button to trigger redirection
    return render_template_string('''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Flask Redirect Button</title>
        </head>
        <body>
            <h1>WIP</h1>
            <form action="/redirect-to-dash" method="get">
                <button type="submit">US2024</button>
            </form>
        </body>
        </html>
    ''')

# Redirect to Dash app at /old/us2024 when the button is clicked
@server.route('/redirect-to-dash')
def redirect_to_dash():
    return redirect('/old/us2024')

