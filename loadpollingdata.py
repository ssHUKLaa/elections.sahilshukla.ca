import pandas as pd
import sqlite3
import math
from datetime import datetime, timedelta

WEEKS_TIME_DELTA = 9

def create_new_table():
    conn = sqlite3.connect('polling_data.db')
    conn.execute('''
    CREATE TABLE IF NOT EXISTS polls (
        poll_id TEXT PRIMARY KEY,
        pollster TEXT,
        numeric_grade REAL,
        state TEXT,
        end_date TEXT,
        sample_size INTEGER,
        population TEXT,
        harris_pct REAL,
        trump_pct REAL,
        moe REAL  -- Add margin of error column
    )
    ''')

def calculate_moe(row, state_averages):
    # Set base margin of error
    moe = (1/math.sqrt(row['sample_size'])) * 100
    
    # Adjust based on population type
    if row['population'] == 'lv':
        moe *= 0.9
    elif row['population'] == 'rv':
        moe *= 1.1
    else:
        moe *=1.15
    
    # Adjust based on numeric grade (higher grade -> lower moe)
    moe *= (1/((5*row['numeric_grade']/3) - 0.25))+0.5
    
    
    # Compare to state averages
    if row['state'] in state_averages:
        avg_harris = state_averages[row['state']]['harris_pct']
        avg_trump = state_averages[row['state']]['trump_pct']

        harris_diff = abs(float(row['harris_pct']) - float(avg_harris))
        trump_diff = abs(float(row['trump_pct']) - float(avg_trump))
        
        # Adjust margin of error based on differences
        moe += (harris_diff + trump_diff) * 0.1
    
    # Ensure moe stays within 3 to 7 range
    return moe

def upload_poll_data_to_db():
    url = 'https://projects.fivethirtyeight.com/polls/data/president_polls.csv'
    data = pd.read_csv(url)
    filtered_data = data[['poll_id', 'pollster', 'numeric_grade', 'state', 'end_date', 
                           'sample_size', 'population', 'party', 'candidate_name', 'pct']]
    filtered_data['state'].fillna('national', inplace=True)
    filtered_data['end_date'] = pd.to_datetime(filtered_data['end_date'])
    filtered_data['numeric_grade'].fillna(1, inplace=True)
    
    # Get polls from the last WEEKS_TIME_DELTA weeks
    two_weeks_ago = datetime.now() - timedelta(weeks=WEEKS_TIME_DELTA)
    filtered_data = filtered_data[filtered_data['end_date'] >= two_weeks_ago]
    filtered_data = filtered_data[filtered_data['party'].isin(['DEM', 'REP'])]

    # Pivot to get pct values for Harris and Trump
    pivoted_data = filtered_data.pivot_table(
        index=['poll_id', 'pollster', 'numeric_grade', 'state', 'end_date', 'sample_size', 'population'],
        columns='candidate_name',
        values='pct',
        aggfunc='first'
    ).reset_index()
    pivoted_data.columns.name = None
    pivoted_data.rename(columns={'Kamala Harris': 'harris_pct', 'Donald Trump': 'trump_pct'}, inplace=True)
    pivoted_data['end_date'] = pivoted_data['end_date'].dt.strftime('%Y-%m-%d')

    # Ensure harris_pct and trump_pct are numeric (float), handle NaN and missing data
    pivoted_data['harris_pct'] = pd.to_numeric(pivoted_data['harris_pct'], errors='coerce').fillna(0)
    pivoted_data['trump_pct'] = pd.to_numeric(pivoted_data['trump_pct'], errors='coerce').fillna(0)

    # Calculate state averages for Harris and Trump as numeric values
    state_averages = pivoted_data.groupby('state')[['harris_pct', 'trump_pct']].mean().to_dict(orient='index')

    # Calculate margin of error and add it to the dataframe
    pivoted_data['moe'] = pivoted_data.apply(calculate_moe, state_averages=state_averages, axis=1)
    
    # Insert data into the SQLite database
    conn = sqlite3.connect('polling_data.db')
    
    for _, row in pivoted_data.iterrows():
        try:
            conn.execute('''
            INSERT INTO polls (poll_id, pollster, numeric_grade, state, end_date, sample_size, population, harris_pct, trump_pct, moe)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (row['poll_id'], row['pollster'], row['numeric_grade'], row['state'], row['end_date'], row['sample_size'], 
                  row['population'], row['harris_pct'], row['trump_pct'], row['moe']))
        except sqlite3.IntegrityError:
            conn.execute('''
            UPDATE polls SET 
                pollster = ?, numeric_grade = ?, state = ?, end_date = ?, sample_size = ?, population = ?, 
                harris_pct = ?, trump_pct = ?, moe = ?
            WHERE poll_id = ?
            ''', (row['pollster'], row['numeric_grade'], row['state'], row['end_date'], row['sample_size'], 
                  row['population'], row['harris_pct'], row['trump_pct'], row['moe'], row['poll_id']))
    
    conn.commit()
    conn.close()
    print("Data uploaded to database successfully!")


def create_results_table():
    conn = sqlite3.connect('polling_data.db')
    conn.execute('''
    CREATE TABLE IF NOT EXISTS election_2020 (
        state TEXT PRIMARY KEY,
        dem_pct REAL,
        rep_pct REAL
    )
    ''')
    conn.commit()
    conn.close()

def process_election_data(csv_file):
    # Read the CSV file
    df = pd.read_csv(csv_file)

    # Filter for Democrat and Republican only
    filtered_df = df[df['party_simplified'].isin(['DEMOCRAT', 'REPUBLICAN'])]

    # Group by state and party and sum the total votes
    grouped_df = filtered_df.groupby(['state', 'party_simplified'])['candidatevotes'].sum().unstack(fill_value=0)

    # Calculate total votes for each state
    grouped_df['total_votes'] = grouped_df.sum(axis=1)


    # Calculate the percentage for each party
    grouped_df['dem_pct'] = (grouped_df['DEMOCRAT'] / grouped_df['total_votes']) * 100
    grouped_df['rep_pct'] = (grouped_df['REPUBLICAN'] / grouped_df['total_votes']) * 100

    # Select relevant columns
    results_df = grouped_df[['dem_pct', 'rep_pct']].reset_index()

    # Insert the results into the database
    conn = sqlite3.connect('polling_data.db')
    for _, row in results_df.iterrows():
        conn.execute('''
        INSERT OR REPLACE INTO election_2020 (state, dem_pct, rep_pct)
        VALUES (?, ?, ?)
        ''', (row['state'], row['dem_pct'], row['rep_pct']))
    
    conn.commit()
    conn.close()
    print("Election results processed and stored in the database.")

create_new_table()
upload_poll_data_to_db()