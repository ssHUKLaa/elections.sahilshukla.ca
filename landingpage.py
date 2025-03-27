from flask import Flask, redirect, render_template
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from datavisualize import server as us2024server

# Initialize Flask app
server = Flask(__name__)

# Main route with button to redirect
@server.route('/')
def home():
    return render_template('index.html')

@server.route('/redirect-to-can2025')
def redirect_to_can2025():
    return redirect('/can2025')

@server.route('/redirect-to-us2024')
def redirect_to_us2024():
    return redirect('/old/us2024')

server.wsgi_app = DispatcherMiddleware(server.wsgi_app, {
    "/old/us2024": us2024server 
})