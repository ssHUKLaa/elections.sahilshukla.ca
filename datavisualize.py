from datetime import datetime, timedelta
import sqlite3
import pandas as pd
import numpy as np
from dash import Dash, dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objects as go
import plotly.express as px



# Connect to SQLite database
def get_data():
    conn = sqlite3.connect('polling_data.db')  # Ensure the path is correct
    query = '''
            SELECT simulation_date, Election_Winner, Harris_Electoral_Votes, Trump_Electoral_Votes
            FROM simulations
            ORDER BY simulation_date DESC
            LIMIT 1000
        '''
    df = pd.read_sql_query(query, conn)
    conn.close()

    # Fill NaN values with 0 before converting to int
    df['Harris_Electoral_Votes'] = df['Harris_Electoral_Votes'].fillna(0).astype(int)
    df['Trump_Electoral_Votes'] = df['Trump_Electoral_Votes'].fillna(0).astype(int)

    harris_wins = df[df['Election_Winner'] == 'Harris'].shape[0]
    trump_wins = df[df['Election_Winner'] == 'Trump'].shape[0]
    return df, harris_wins, trump_wins

def pullSpecialPCTS():
    conn = sqlite3.connect('polling_data.db')

    # Define the states of interest
    states_of_interest = ['Pennsylvania', 'Wisconsin', 'Michigan', 
                        'Nevada', 'Arizona', 'Georgia', 'North_Carolina']

    # Construct the query to select the desired columns
    query = f"""
    SELECT 
        {' , '.join([f"{state}_Harris" for state in states_of_interest])},
        {' , '.join([f"{state}_Trump" for state in states_of_interest])}
    FROM simulations
    ORDER BY simulation_date DESC
    LIMIT 1000
    """

    # Execute the query and fetch the results into a DataFrame
    df = pd.read_sql_query(query, conn)

    # Close the database connection
    conn.close()
    return df

def dbPullP_E_Winner():
    conn = sqlite3.connect('polling_data.db')
    cursor = conn.cursor()

    # Query for average national votes
    cursor.execute("SELECT AVG(national_Harris), AVG(national_Trump) FROM simulations ORDER BY simulation_date DESC LIMIT 1000")
    avg_harris, avg_trump = cursor.fetchone()
    cursor.execute("SELECT AVG(Harris_Electoral_Votes), AVG(Trump_Electoral_Votes) FROM simulations ORDER BY simulation_date DESC LIMIT 1000")
    avg_harris_e, avg_trump_e = cursor.fetchone()

    # Close the connection
    conn.close()
    return avg_harris,avg_trump, avg_harris_e,avg_trump_e

latest_data, harris_wins, trump_wins = get_data()
none_wins = 1000 - harris_wins - trump_wins
latest_simulation_date = latest_data['simulation_date'].values[0] if not latest_data.empty else "No data available"
SIMULATION_NAT_HARRIS, SIMULATION_NAT_TRUMP, SIMULATION_ELE_HARRIS, SIMULATION_ELE_TRUMP = dbPullP_E_Winner()
P_Winner=""
E_Winner=""
popular_vote_margin=0
electoral_vote_margin=0
if SIMULATION_NAT_HARRIS>SIMULATION_NAT_TRUMP:
    P_Winner = "Harris"
    popular_vote_margin = '%.3f'%(SIMULATION_NAT_HARRIS - SIMULATION_NAT_TRUMP)
else:
    P_Winner = "Trump"
    popular_vote_margin = '%.3f'%(SIMULATION_NAT_TRUMP - SIMULATION_NAT_HARRIS)

if SIMULATION_ELE_HARRIS>SIMULATION_ELE_TRUMP:
    E_Winner = "Harris"
    electoral_vote_margin = int(SIMULATION_ELE_HARRIS - SIMULATION_ELE_TRUMP)

else:
    E_Winner = "Trump"
    popular_vote_margin = int(SIMULATION_ELE_TRUMP - SIMULATION_ELE_HARRIS)
# Initialize Dash app
app = Dash(__name__,title="Shuklas Election Predictions")
server = app.server


# Define layout
app.layout = html.Div([
    html.Link(rel="preconnect", href="https://fonts.googleapis.com"),
    html.Link(rel="preconnect", href="https://fonts.gstatic.com", crossOrigin=""),
    html.Link(href="https://fonts.googleapis.com/css2?family=Aldrich&display=swap", rel="stylesheet"),
    html.H2(
        f"UPDATED: {latest_simulation_date} - Polling has been bad for Harris in the last 2 days in key swing states.",  # Dynamically show latest time
        style={'font-family': 'Aldrich','textAlign': 'center', 'color': 'gray', 'fontSize': '15px', 'marginBottom': '10px'}  # Style for the updated header
    ),
    html.H2(
        html.A(
            "Read my article for more details on the model.",
            href="https://medium.com/@sahilshukla_9303/how-do-you-predict-the-unpredictable-an-electoral-simulation-model-for-the-2024-election-182279531246",
            target="_blank",  # Opens the link in a new tab
            style={'font-family': 'Aldrich', 'color': 'blue', 'textDecoration': 'underline'}  # Style for the clickable link
        ),
        style={'textAlign': 'center', 'fontSize': '15px', 'marginBottom': '10px'}  # Style for the header
    ),
    html.H1(
        "Sahil Shukla Predicts The Election.",
        style={'font-family': 'Aldrich','textAlign': 'center',  'fontSize': '36px','marginTop': '0px', 'marginBottom': '5px'}),
    html.P(f"Kamala Harris Wins {harris_wins} times", 
            style={'font-family': 'Aldrich','textAlign': 'center', 'fontSize': '24px', 'marginTop': '5px', 'marginBottom': '0px', 'color': 'blue','opacity':'0.8'}),
    html.P(f"Donald Trump Wins {trump_wins} times", 
            style={'font-family': 'Aldrich','textAlign': 'center', 'fontSize': '24px', 'marginTop': '5px', 'marginBottom': '0px', 'color': 'red','opacity':'0.8'}),
    html.P("Out of 1000 simulations of the 2024 elections.", 
            style={'font-family': 'Aldrich','textAlign': 'center', 'fontSize': '24px', 'marginTop': '5px', 'marginBottom': '0px', 'color': 'gray','opacity':'0.8'}),
    html.P(f"There is a tie {none_wins} times.", 
            style={'font-family': 'Aldrich','textAlign': 'center', 'fontSize': '20px', 'marginTop': '5px', 'marginBottom': '0px', 'color': 'gray','opacity':'0.8'}),
    dcc.Graph(
        id='electoral-votes-graph',
        config={
            'displayModeBar': False  # Disable the mode bar
        },
        style={'marginBottom': '0px','marginTop':'0px' }
    ),
    html.H1(
        "How Do The Swing States Break?",
        style={'font-family': 'Aldrich','textAlign': 'center',  'fontSize': '36px','marginTop': '20px', 'marginBottom': '5px'}),
    html.P(id='lead-text', 
           style={'font-family': 'Aldrich', 'textAlign': 'center', 'fontSize': '14px', 'marginTop': '5px', 'marginBottom': '0px', 'color': 'black', 'opacity': '0.8'}),
    dcc.Graph(
        id='bar-graph',  # Unique ID for the bar graph
        config={'displayModeBar': False},
        style={'marginTop': '20px'}  # Margin to separate from the other graph
    ),
    html.H1(
        "What Does The National Map Look Like?",
        style={'font-family': 'Aldrich','textAlign': 'center',  'fontSize': '36px','marginTop': '20px', 'marginBottom': '5px'}),
    html.P(f"My simulations Predict that...", 
            style={'font-family': 'Aldrich','textAlign': 'center', 'fontSize': '16px', 'marginTop': '5px', 'marginBottom': '0px', 'color': 'grey','opacity':'0.8'}),
    html.P(f"{P_Winner} Wins the Popular Vote By {popular_vote_margin}%", 
            style={'font-family': 'Aldrich','textAlign': 'center', 'fontSize': '20px', 'marginTop': '5px', 'marginBottom': '0px', 'color': 'black','opacity':'0.8'}),
    html.P(f"{E_Winner} Wins the Electoral College By {electoral_vote_margin} Votes", 
            style={'font-family': 'Aldrich','textAlign': 'center', 'fontSize': '20px', 'marginTop': '5px', 'marginBottom': '0px', 'color': 'black','opacity':'0.8'}),
    html.P(f"On Average", 
            style={'font-family': 'Aldrich','textAlign': 'center', 'fontSize': '20px', 'marginTop': '5px', 'marginBottom': '0px', 'color': 'black','opacity':'0.8'}),
    dcc.Graph(
        id='choropleth-map',
        config={'displayModeBar': False},
        ),
    html.H1(
        "How Has The Race Changed Over Time?",
        style={'font-family': 'Aldrich','textAlign': 'center',  'fontSize': '36px','marginTop': '20px', 'marginBottom': '5px'}),
    html.P(f"The United States will hold its election on November 5th, 2024. My predictions will update until that day.", 
            style={'font-family': 'Aldrich','textAlign': 'center', 'fontSize': '20px', 'marginTop': '5px', 'marginBottom': '0px', 'color': 'black','opacity':'0.8'}),
    dcc.Graph(
        id='line-graph',
        config={'displayModeBar': False},
        ),
])

# Callback to update graph
@app.callback(
    Output('electoral-votes-graph', 'figure'),
    Input('electoral-votes-graph', 'id')  # Dummy input to trigger on load
)
 
def update_graph(_):
    df, harris_wins, trump_wins = get_data()

    # Create lists to store x and y positions for the dots
    x_positions = []
    y_positions = []
    labels = []
    candidate_colors = []
    candidate_opacities = []
    harris_x_positions = {}
    trump_x_positions = {}
    shift_value = 13
    for idx, row in df.iterrows():
        if row['Election_Winner'] == 'Harris':
            # Position Harris's votes on the left side, with 270 at the line
            x_pos_utilize=((-5*(row['Harris_Electoral_Votes'] - 270)))  # Shift left by 270
            x_pos = round(x_pos_utilize / shift_value) * shift_value
            if x_pos==0:
                x_pos=-shift_value
            if x_pos not in harris_x_positions:
                harris_x_positions[x_pos] = 0
            else:
                harris_x_positions[x_pos]-=10

            
            y_positions.append(-harris_x_positions[x_pos]*6)  
            x_positions.append(x_pos)
            candidate_colors.append('blue')
            opacity = (row['Harris_Electoral_Votes'] / 538) ** 0.5
            candidate_opacities.append(opacity)
            labels.append(
                f"<b>&nbsp;&nbsp;Electoral Votes&nbsp;&nbsp;</b><br>"
                f"&nbsp;&nbsp;<span style='color: blue;'>Harris:</span>&nbsp;&nbsp;&nbsp;&nbsp;"
                f"<span style='color: red;'>Trump:</span><br>"
                f"&nbsp;&nbsp;&nbsp;&nbsp;<span style='color: blue;'>{row['Harris_Electoral_Votes']}</span>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                f"<span style='color: red;'>{row['Trump_Electoral_Votes']}</span>&nbsp;&nbsp;"
            )
        elif row['Election_Winner'] == 'Trump':
            x_pos_utilize=((5*(row['Trump_Electoral_Votes'] - 270)))  # Shift left by 270
            x_pos = round(x_pos_utilize / shift_value) * shift_value
            if x_pos==0:
                x_pos=+shift_value
            if x_pos not in trump_x_positions:
                trump_x_positions[x_pos] = 0
            else:
                trump_x_positions[x_pos]+=10

            
            y_positions.append(trump_x_positions[x_pos]*6)  # Using index for y position
            x_positions.append(x_pos)
            # Position Trump's votes on the right side, with 270 at the line

            candidate_colors.append('red')  # Color for Trump
            opacity = (row['Trump_Electoral_Votes'] / 538) ** 0.5
            candidate_opacities.append(opacity)
            labels.append(
                f"<b>&nbsp;&nbsp;Electoral Votes&nbsp;&nbsp;</b><br>"
                f"&nbsp;&nbsp;<span style='color: red;'>Trump:</span>&nbsp;&nbsp;&nbsp;&nbsp;"
                f"<span style='color: blue;'>Harris:</span><br>"
                f"&nbsp;&nbsp;&nbsp;&nbsp;<span style='color: red;'>{row['Trump_Electoral_Votes']}</span>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                f"<span style='color: blue;'>{row['Harris_Electoral_Votes']}</span>&nbsp;&nbsp;"
            )

    # Create a scatter plot with manually positioned dots
    fig = go.Figure(data=go.Scatter(
        x=x_positions,
        y=y_positions,
        mode='markers',
        marker=dict(color=candidate_colors, size=5,opacity=candidate_opacities),
        text=labels,
        hoverinfo='text',
        hoverlabel=dict(bgcolor='white', font=dict(color='black'), bordercolor='black'  # Border color with opacity
    )))

    fig.add_shape(type="rect",
                  x0=-600, x1=-110, y0=-100, y1=-150,  # Coordinates for Harris bar
                  fillcolor='blue', opacity=0.8,
                  line_color='blue')

    fig.add_shape(type="rect",
                  x0=-100, x1=-10, y0=-100, y1=-150,  # Coordinates for Harris bar
                  fillcolor='blue', opacity=0.5,
                  line_color='blue')


    fig.add_shape(type="rect",
                  x0=110, x1=600, y0=-100, y1=-150,  # Coordinates for Trump bar
                  fillcolor='red', opacity=0.8,
                  line_color='red')

    fig.add_shape(type="rect",
                  x0=10, x1=100, y0=-100, y1=-150,  # Coordinates for Trump bar
                  fillcolor='red', opacity=0.5,
                  line_color='red')
    

    # Add a vertical line at x=0
    fig.add_shape(
        type="line",
        x0=0, y0=-0.5,  # Start just below the first dot
        x1=0, y1=max(y_positions)+30,  # Extend to just above the last dot
        line=dict(color="black", width=2, dash="dash")  # Line style
    )

    # Update layout
    fig.update_layout(
        margin=dict(l=10, r=10, t=0, b=10),
        plot_bgcolor='rgba(0, 0, 0, 0)',  # Remove plot background
        paper_bgcolor='rgba(0, 0, 0, 0)',
        xaxis_title='Electoral Votes',
        xaxis=dict(
            tickvals=[-538, -100,0, 100, 538],  # Updated for correct positioning
            ticktext=["D + 538", "D + 100","0", "R + 100", "R + 538"],  # Custom tick labels
            range=[-600, 600],  # Setting the x-axis range
            tickangle=0  # Rotate ticks to be horizontal
        ),
        yaxis=dict(showticklabels=False),  # Hide y-axis tick labels
        dragmode=False,
        showlegend=False  # Hide legend since colors indicate the candidate
        
    )

    return fig

@app.callback(
    [Output('bar-graph', 'figure'),
     Output('lead-text', 'children')],
    Input('bar-graph', 'id')  # Dummy input to trigger on load
)

def update_bar_graph(_):
    data = pullSpecialPCTS()
    
    # Averages for Harris and Trump
    harris_averages = data.iloc[:, 0:7].mean().tolist()  # Averages for Harris
    trump_averages = data.iloc[:, 7:14].mean().tolist()  # Averages for Trump

    # State names for annotations
    states_of_interest = ['Pennsylvania', 'Wisconsin', 'Michigan', 
                          'Nevada', 'Arizona', 'Georgia', 'North Carolina']

    # Create vertical spacing for bars
    bar_height = 2  # Height of each bar
    y_positions = [i * (bar_height + 3) for i in range(len(states_of_interest))]  # Add extra space

    # Create the horizontal bar graph
    harris_hover_text = [f"{state}: {avg:.2f}%" for state, avg in zip(states_of_interest, harris_averages)]
    trump_hover_text = [f"{state}: {avg:.2f}%" for state, avg in zip(states_of_interest, trump_averages)]

    
    fig = go.Figure(data=[
        go.Bar(
            x=harris_averages,
            y=y_positions,
            orientation='h',
            marker_color='blue',
            showlegend=False,
            width=bar_height,
            text=harris_hover_text,  # Add hover text for Harris
            hoverinfo='text',  # Specify that we want to show the hover text
            textposition='none'  # Ensure no text appears on the bar
        ),
        go.Bar(
            x=trump_averages,
            y=y_positions,
            orientation='h',
            marker_color='red',
            base=harris_averages,
            showlegend=False,
            width=bar_height,
            text=trump_hover_text,  # Add hover text for Trump
            hoverinfo='text',  # Specify that we want to show the hover text
            textposition='none'  # Ensure no text appears on the bar
        )
    ])

    harris_leads_states = [states_of_interest[i] for i in range(len(states_of_interest)) if harris_averages[i] > trump_averages[i]]
    trump_leads_states = [states_of_interest[i] for i in range(len(states_of_interest)) if harris_averages[i] < trump_averages[i]]
    # Format the states into a string
    if harris_leads_states:
        states_str = ", ".join(harris_leads_states)
        trump_leads_states_str = ", ".join(trump_leads_states)
        lead_text = f"In my simulations, Kamala Harris currently leads in {states_str}, while Donald Trump leads in {trump_leads_states_str}"
    else:
        lead_text = "In my simulations, neither candidate currently leads in any states."



    # Add annotations for each state above the bars
    for i in range(len(states_of_interest)):
        fig.add_annotation(
            x=(harris_averages[i] + trump_averages[i]) / 2,  # Position at the midpoint of the two bars
            y=y_positions[i] + 1,  # Position slightly above the bar
            text=f"{states_of_interest[i]} (+/-3)",  # Text to display
            showarrow=False,  # Do not show arrow
            font=dict(color='black',family='Aldrich'),  # Font color
            xanchor='center',  # Center the text between the bars
            yanchor='bottom'  # Position text at the bottom
        )
        fig.add_annotation(
            x=25,  # Position on the left side of the bar
            y=y_positions[i] + 1,  # Position slightly above the bar
            text=f"Kamala: {harris_averages[i]:.2f}",  # Text to display
            showarrow=False,  # Do not show arrow
            font=dict(color='black', family='Aldrich'),  # Font color and family
            xanchor='right',  # Anchor text to the right
            yanchor='bottom'  # Position text at the bottom
        )

        # Donald Trump annotation (right)
        fig.add_annotation(
            x=75,  # Position on the right side of the bar
            y=y_positions[i] + 1,  # Position slightly above the bar
            text=f"Trump: {trump_averages[i]:.2f}",  # Text to display
            showarrow=False,  # Do not show arrow
            font=dict(color='black', family='Aldrich'),  # Font color and family
            xanchor='left',  # Anchor text to the left
            yanchor='bottom'  # Position text at the bottom
        )

        # Add a translucent box around each bar
        fig.add_shape(
            type='rect',
            x0=47,x1=53,
            y0=y_positions[i] - 1, y1=y_positions[i] + 1,  # Box centered on each bar
            fillcolor='purple',  # Purple fill color
            opacity=0.75,  # 20% opacity for translucence
            line=dict(width=0)  # No border around the box
        )

    # Update layout to remove labels, ticks, and categories
    fig.update_layout(
        barmode='stack',
        xaxis=dict(
            range=[0, 100],
            showticklabels=False,  # Show x-axis labels
            zeroline=False  # Remove the zero line
        ),
        yaxis=dict(
            showticklabels=False,  # Hide y-axis labels (as we use annotations)
            zeroline=False  # Remove the zero line
        ),
        dragmode=False,
        plot_bgcolor='rgba(0, 0, 0, 0)',  # Transparent background
        paper_bgcolor='rgba(0, 0, 0, 0)',  # Transparent paper background
        margin=dict(l=10, r=10, t=0, b=0),  # Adjust margins if needed
    )

    return fig, lead_text

state_abbreviations = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New_Hampshire": "NH",
    "New_Jersey": "NJ",
    "New_Mexico": "NM",
    "New_York": "NY",
    "North_Carolina": "NC",
    "North_Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode_Island": "RI",
    "South_Carolina": "SC",
    "South_Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West_Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
    "District_of_Columbia": "DC"
}
def get_map_data():
    electoral_votes = {
        'Alabama': 9, 'Alaska': 3, 'Arizona': 11, 'Arkansas': 6, 'California': 54,
        'Colorado': 10, 'Connecticut': 7, 'Delaware': 3, 'Florida': 30, 'Georgia': 16,
        'Hawaii': 4, 'Idaho': 4, 'Illinois': 19, 'Indiana': 11, 'Iowa': 6,
        'Kansas': 6, 'Kentucky': 8, 'Louisiana': 8, 'Maine': 2, 'Maine_CD_1': 1, 'Maine_CD_2': 1,
        'Maryland': 10, 'Massachusetts': 11, 'Michigan': 15, 'Minnesota': 10, 'Mississippi': 6,
        'Missouri': 10, 'Montana': 4, 'Nebraska': 4, 'Nebraska_CD_2': 1, 'Nevada': 6, 'New_Hampshire': 4,
        'New_Jersey': 14, 'New_Mexico': 5, 'New_York': 28, 'North_Carolina': 16,
        'North_Dakota': 3, 'Ohio': 17, 'Oklahoma': 7, 'Oregon': 8, 'Pennsylvania': 19,
        'Rhode_Island': 4, 'South_Carolina': 9, 'South_Dakota': 3, 'Tennessee': 11,
        'Texas': 40, 'Utah': 6, 'Vermont': 3, 'Virginia': 13, 'Washington': 12,
        'West_Virginia': 4, 'Wisconsin': 10, 'Wyoming': 3, 'national': 0,  # Added national as 0 votes
        'District_of_Columbia': 3
    }
    # Create an empty dictionary to hold the Harris percentages
    avg_diff = {}
    final_data = {
        'state': [],
        'value': [],
        'harris_avg': [],
        'trump_avg': []
    }

    # Connect to the database
    conn = sqlite3.connect('polling_data.db')
    cursor = conn.cursor()

    # Iterate over the states and append '_Harris' to access the correct columns
    for state in electoral_votes.keys():
        harris_column = state + '_Harris'
        trump_column = state + '_Trump'
        
        # Query the Harris percentage for each state
        cursor.execute(f"SELECT AVG({harris_column}) FROM simulations ORDER BY simulation_date DESC LIMIT 1000")
        harris_avg = cursor.fetchone()[0]
        cursor.execute(f"SELECT AVG({trump_column}) FROM simulations ORDER BY simulation_date DESC LIMIT 1000")
        trump_avg = cursor.fetchone()[0]

        # Store the result in the dictionary
        avg_diff[state]=harris_avg-trump_avg
        state_abbr = state_abbreviations.get(state)
        if state_abbr:  
            final_data['state'].append(state_abbr)
            final_data['value'].append(avg_diff[state])
            final_data['harris_avg'].append(harris_avg)
            final_data['trump_avg'].append(trump_avg)

    # Close the connection
    conn.close()

    return final_data

@app.callback(
    Output('choropleth-map', 'figure'),
    Input('choropleth-map', 'id')  # Adjust based on your inputs
)
def update_map(_):
    # Retrieve data based on the selected input
    df = get_map_data()  # Replace with your data retrieval logic

    custom_color_scale = [
        [0, 'darkred'],
        [0.45, 'red'],
        [0.5, 'purple'],
        [0.53, 'rgba(3, 138, 255, 1)'],
        [0.55,'blue'],
        [1, 'darkblue']
    ]

    max_value = 100  
    df=pd.DataFrame(df)
    df['normalized_value'] = (((df['value'] / max_value) + 1)/2)
    df['custom_tooltip'] = [
        f"<span style='color: {'blue' if value > 0 else 'red'};'>{'Harris' if value > 0 else 'Trump'}</span> leads in {state} by {abs(value):.2f}%<br>"
        f"<span style='color: blue;'>Harris</span>: {harris_avg:.2f}% of the vote<br>"
        f"<span style='color: red;'>Trump</span>: {trump_avg:.2f}% of the vote"
        for state, value, harris_avg, trump_avg in zip(df['state'], df['value'], df['harris_avg'], df['trump_avg'])
    ]

    fig = px.choropleth(
        df,
        locations='state',
        locationmode='USA-states',
        color='normalized_value',  # The column to color the states by
        color_continuous_scale=custom_color_scale,  # Choose a color scale
        range_color=(0,1),
        scope='usa',  # Focus on the USA
    )
    fig.update_traces(
        hovertemplate='%{customdata[0]}<extra></extra>',
        customdata=df[['custom_tooltip']],
        hoverlabel=dict(
            bgcolor='white',  # Set background color to white
            font_size=14,     # Set font size
            font_color='black'  # Set font color to black
        )
    )

    fig.update_layout(
        title_text='Election Results by State',
        geo=dict(
            showlakes=False,
            coastlinecolor="white",  # Customize coastline color
            lakecolor="lightblue",  # Customize lake color
        ),
        xaxis=dict(showticklabels=False),  # Hide x-axis ticks and labels
        yaxis=dict(showticklabels=False),   # Hide y-axis ticks and labels
        showlegend=False,
        coloraxis_showscale=False,
        dragmode=False,
        margin=dict(l=10, r=10, t=0, b=0)
    )

    return fig

@app.callback(
    Output('line-graph', 'figure'),
    Input('line-graph', 'id')  # Adjust based on your inputs
)
def update_line_graph(_):
    conn = sqlite3.connect('polling_data.db')
    end_date = datetime(2024, 11, 5)
    start_date = datetime.now()-timedelta(days=5)
    
    # Query to get average national_harris and national_trump for each date in the range
    query = '''
        SELECT DATE(simulation_date) AS simulation_date, 
            AVG(national_harris) AS avg_harris, 
            AVG(national_trump) AS avg_trump,
            MIN(simulation_date) AS earliest_time,
            COUNT(*) AS count_entries  -- Count the number of entries for each date
        FROM simulations
        GROUP BY DATE(simulation_date)  -- Group by date to get averages
        ORDER BY simulation_date;  -- Optional: Order by date
    '''
    
    df = pd.read_sql_query(query, conn,)
    conn.close()

    fig = px.line(
        df, 
        x='simulation_date', 
        y=['avg_harris', 'avg_trump'],
        labels={'value': 'Average Votes', 'simulation_date': 'Date'},
        range_x=['earliest_time',datetime.now()]
    )
    fig.update_yaxes(range=[0, 100])
    fig.update_layout(
        xaxis_title='Date',
        legend_title='Candidates',
        showlegend=False,
        hovermode='x unified',
        dragmode=False,
        margin=dict(l=10, r=10, t=0, b=0)
    )
    '''
    fig.add_shape(
        type='line',
        xref='x', yref='y',
        x0=end_date,x1=end_date,
        y0=0, y1=100,  # Adjust y1 if you want it to extend beyond 100
        line=dict(
            color='black',
            dash='dash',  # Dashed line
            width=2,
        ),
    )
    '''

    return fig


if __name__ == '__main__':
    app.run_server(debug=False, host="0.0.0.0", port=8050)
