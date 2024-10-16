
# Electoral votes per state
electoral_votes = {
    'Alabama': 9, 'Alaska': 3, 'Arizona': 11, 'Arkansas': 6, 'California': 54,
    'Colorado': 10, 'Connecticut': 7, 'Delaware': 3, 'Florida': 30, 'Georgia': 16,
    'Hawaii': 4, 'Idaho': 4, 'Illinois': 19, 'Indiana': 11, 'Iowa': 6,
    'Kansas': 6, 'Kentucky': 8, 'Louisiana': 8, 'Maine': 2,'Maine CD-1': 1,'Maine CD-2':1, 'Maryland': 10,
    'Massachusetts': 11, 'Michigan': 15, 'Minnesota': 10, 'Mississippi': 6,
    'Missouri': 10, 'Montana': 4, 'Nebraska': 4, 'Nebraska CD-2': 1, 'Nevada': 6, 'New Hampshire': 4,
    'New Jersey': 14, 'New Mexico': 5, 'New York': 28, 'North Carolina': 16,
    'North Dakota': 3, 'Ohio': 17, 'Oklahoma': 7, 'Oregon': 8, 'Pennsylvania': 19,
    'Rhode Island': 4, 'South Carolina': 9, 'South Dakota': 3, 'Tennessee': 11,
    'Texas': 40, 'Utah': 6, 'Vermont': 3, 'Virginia': 13, 'Washington': 12,
    'West Virginia': 4, 'Wisconsin': 10, 'Wyoming': 3, 'national': 0,  # Added national as 0 votes
    'District of Columbia': 3
}

import random
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed

WEEKS_TIME_DELTA = 3
NUM_SIMULATIONS = 1000
NUM_WORKERS = 10

TRUMP_TRAILOFF_PCT_MAX = 0.01
DAYS_SINCE_MAJOR_EVENT = 1
UNCOMMITED_TRUMP_BREAKOFF = 0.5
UNCOMMITED_HARRIS_BREAKOFF = 0.5
import sqlite3
import hashlib

def create_simulation_table_with_all_states():
    conn = sqlite3.connect('polling_data.db')
    # Create the table with a column for each state (both Harris and Trump percentages)
    conn.execute('''
    CREATE TABLE IF NOT EXISTS simulations (
        id TEXT PRIMARY KEY,
        simulation_date TEXT,
        Election_Winner TEXT,
        Harris_Electoral_Votes INTEGER,
        Trump_Electoral_Votes INTEGER,
        Alabama_Harris REAL, Alabama_Trump REAL,
        Alaska_Harris REAL, Alaska_Trump REAL,
        Arizona_Harris REAL, Arizona_Trump REAL,
        Arkansas_Harris REAL, Arkansas_Trump REAL,
        California_Harris REAL, California_Trump REAL,
        Colorado_Harris REAL, Colorado_Trump REAL,
        Connecticut_Harris REAL, Connecticut_Trump REAL,
        Delaware_Harris REAL, Delaware_Trump REAL,
        Florida_Harris REAL, Florida_Trump REAL,
        Georgia_Harris REAL, Georgia_Trump REAL,
        Hawaii_Harris REAL, Hawaii_Trump REAL,
        Idaho_Harris REAL, Idaho_Trump REAL,
        Illinois_Harris REAL, Illinois_Trump REAL,
        Indiana_Harris REAL, Indiana_Trump REAL,
        Iowa_Harris REAL, Iowa_Trump REAL,
        Kansas_Harris REAL, Kansas_Trump REAL,
        Kentucky_Harris REAL, Kentucky_Trump REAL,
        Louisiana_Harris REAL, Louisiana_Trump REAL,
        Maine_Harris REAL, Maine_Trump REAL,
        Maine_CD1_Harris REAL, Maine_CD1_Trump REAL,
        Maine_CD2_Harris REAL, Maine_CD2_Trump REAL,
        Maryland_Harris REAL, Maryland_Trump REAL,
        Massachusetts_Harris REAL, Massachusetts_Trump REAL,
        Michigan_Harris REAL, Michigan_Trump REAL,
        Minnesota_Harris REAL, Minnesota_Trump REAL,
        Mississippi_Harris REAL, Mississippi_Trump REAL,
        Missouri_Harris REAL, Missouri_Trump REAL,
        Montana_Harris REAL, Montana_Trump REAL,
        Nebraska_Harris REAL, Nebraska_Trump REAL,
        Nebraska_CD2_Harris REAL, Nebraska_CD2_Trump REAL,
        Nevada_Harris REAL, Nevada_Trump REAL,
        New_Hampshire_Harris REAL, New_Hampshire_Trump REAL,
        New_Jersey_Harris REAL, New_Jersey_Trump REAL,
        New_Mexico_Harris REAL, New_Mexico_Trump REAL,
        New_York_Harris REAL, New_York_Trump REAL,
        North_Carolina_Harris REAL, North_Carolina_Trump REAL,
        North_Dakota_Harris REAL, North_Dakota_Trump REAL,
        Ohio_Harris REAL, Ohio_Trump REAL,
        Oklahoma_Harris REAL, Oklahoma_Trump REAL,
        Oregon_Harris REAL, Oregon_Trump REAL,
        Pennsylvania_Harris REAL, Pennsylvania_Trump REAL,
        Rhode_Island_Harris REAL, Rhode_Island_Trump REAL,
        South_Carolina_Harris REAL, South_Carolina_Trump REAL,
        South_Dakota_Harris REAL, South_Dakota_Trump REAL,
        Tennessee_Harris REAL, Tennessee_Trump REAL,
        Texas_Harris REAL, Texas_Trump REAL,
        Utah_Harris REAL, Utah_Trump REAL,
        Vermont_Harris REAL, Vermont_Trump REAL,
        Virginia_Harris REAL, Virginia_Trump REAL,
        Washington_Harris REAL, Washington_Trump REAL,
        West_Virginia_Harris REAL, West_Virginia_Trump REAL,
        Wisconsin_Harris REAL, Wisconsin_Trump REAL,
        Wyoming_Harris REAL, Wyoming_Trump REAL
    )
    ''')
    conn.commit()
    conn.close()




def fetch_poll_data(conn):
    two_weeks_ago = datetime.now() - timedelta(weeks=WEEKS_TIME_DELTA)
    query = f'''
        SELECT state, harris_pct, trump_pct, moe
        FROM polls
        WHERE DATE(end_date) >= DATE(?) OR
              state NOT IN (SELECT DISTINCT state FROM polls WHERE DATE(end_date) >= DATE(?))
    '''
    data = pd.read_sql(query, conn, params=[two_weeks_ago, two_weeks_ago])
    return data

def get_2020_results(state):
    conn = sqlite3.connect('polling_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT dem_pct, rep_pct FROM election_2020 WHERE state = ?
    ''', (state,))
    result = cursor.fetchone()
    conn.close()
    return result

def simulate_election(polls, electoral_votes):
    print('Simulating election ...')
    electoral_results = {"Harris": 0, "Trump": 0}
    state_results = []
    no_poll_states = []
    db_state_results = []

    TRUMP_TRAILOFF_VAL = random.uniform(0.025*DAYS_SINCE_MAJOR_EVENT,TRUMP_TRAILOFF_PCT_MAX)

    nat_movement = 10
    nat_dev = nat_movement*0.001
    nat_moe = np.random.normal(loc=0,scale=nat_dev)
    all_states = electoral_votes.keys()

    # Loop through all states, whether they have polling data or not
    for state in all_states:
        state_polls = polls[polls['state'] == state]

        if state_polls.empty:
            # No polling data; use 2020 results
            state_2020_results = get_2020_results(state.upper())
            if state_2020_results:
                dem_pct, rep_pct  = state_2020_results
                # Apply a random error between 3 and 7%
                error = random.uniform(-3, 3)
                harris_adjusted = dem_pct + error - TRUMP_TRAILOFF_VAL
                trump_adjusted = rep_pct - error + TRUMP_TRAILOFF_VAL
                
                if harris_adjusted > trump_adjusted:
                    electoral_results["Harris"] += electoral_votes[state]
                    state_results.append((state, 'Harris', harris_adjusted - trump_adjusted))
                else:
                    electoral_results["Trump"] += electoral_votes[state]
                    state_results.append((state, 'Trump', trump_adjusted - harris_adjusted))
                db_state_results.append((state,"Harris",harris_adjusted,'Trump',trump_adjusted))
                continue
            else:
                no_poll_states.append(state)
                continue

        harris_pcts = []
        trump_pcts = []

        # Apply margin of error for each poll in the state
        for _, row in state_polls.iterrows():

            randmoe = random.uniform(-row['moe'], row['moe']) + nat_moe
            harris_adjusted = row['harris_pct'] - randmoe - TRUMP_TRAILOFF_VAL
            trump_adjusted = row['trump_pct'] + randmoe + TRUMP_TRAILOFF_VAL

            if ((harris_adjusted + trump_adjusted) < 100):
                pct_uncommited = 100 - (harris_adjusted + trump_adjusted)
                trump_extra = pct_uncommited * UNCOMMITED_TRUMP_BREAKOFF
                harris_extra = pct_uncommited * UNCOMMITED_HARRIS_BREAKOFF
                harris_adjusted+=harris_extra
                trump_adjusted+=trump_extra
            harris_pcts.append(harris_adjusted)
            trump_pcts.append(trump_adjusted)

        # Calculate the averages after adjustment
        avg_harris = sum(harris_pcts) / len(harris_pcts)
        avg_trump = sum(trump_pcts) / len(trump_pcts)

        # Calculate the difference in percentage points
        point_diff = avg_harris - avg_trump

        if avg_harris > avg_trump:
            electoral_results["Harris"] += electoral_votes[state]
            state_results.append((state, 'Harris', point_diff))
        else:
            electoral_results["Trump"] += electoral_votes[state]
            state_results.append((state, 'Trump', -point_diff))
        db_state_results.append((state,"Harris",avg_harris,'Trump',avg_trump))

    return electoral_results, state_results, db_state_results

def simulate_multiple_times(num_simulations, polls, electoral_votes):
    harris_wins = 0
    trump_wins = 0
    all_state_results = []
    all_electoral_votes = []
    all_db_state_values = []

    for _ in range(num_simulations):
        results, state_results, db_state_results = simulate_election(polls, electoral_votes)
        
        # Track who won
        if results["Harris"] > results["Trump"]:
            harris_wins += 1
        else:
            trump_wins += 1

        # Store the state results and electoral votes for this simulation
        all_state_results.append(state_results)
        all_electoral_votes.append(results)
        all_db_state_values.append(db_state_results)

    return harris_wins, trump_wins, all_state_results, all_electoral_votes,all_db_state_values

def generate_hash_key(simulation_data):
    # Generate a hash key based on the simulation data
    data_str = ''.join([f"{state}{harris_pct}{trump_pct}" for state, _, harris_pct, _, trump_pct in simulation_data])
    return hashlib.sha256(data_str.encode('utf-8')).hexdigest()

def sanitize_column_name(state_name):
    return state_name.replace(' ', '_').replace('-', '_')

def uploadDataToDB(data,all_electoral_votes_total,conn):
    simulation_date=None
    # Sanitize the column names to make them SQLite-friendly
    columns = ', '.join([f"{sanitize_column_name(state)}_Harris, {sanitize_column_name(state)}_Trump" for state in electoral_votes.keys()])
    placeholders = ', '.join(['?' for _ in range(len(electoral_votes.keys()) * 2)])

    # Loop through the outer simulation list
    i=0
    for sim_data in data:
        state_data = []
        e_ev_harris = all_electoral_votes_total[i]["Harris"]
        e_ev_trump = all_electoral_votes_total[i]["Trump"]
        e_winner = ""
        if e_ev_harris>e_ev_trump:
            e_winner = "Harris"
        elif e_ev_harris<e_ev_trump:
            e_winner = "Trump"
        else:
            e_winner = "Tie"
        # Loop through each state in the inner list of the simulation
        for state, _, harris_pct, _, trump_pct in sim_data:
            state_data.append(harris_pct)
            state_data.append(trump_pct)

        # Generate a hash key for the row
        hash_key = generate_hash_key(sim_data)

        # Use the current date if none is provided
        if not simulation_date:
            simulation_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Insert the row into the database with the sanitized column names
        conn.execute(f'''
        INSERT INTO simulations (id, simulation_date, Election_Winner, Harris_Electoral_Votes, Trump_Electoral_Votes, {columns})
        VALUES (?, ?, ?, ?, ?, {placeholders})
        ''', (hash_key, simulation_date, e_winner, e_ev_harris, e_ev_trump,*state_data))
        i+=1
    conn.commit()

def run_simulations_parallel():
    conn = sqlite3.connect('polling_data.db')
    poll_data = fetch_poll_data(conn)
    
    simulations_per_worker = NUM_SIMULATIONS // NUM_WORKERS
    remaining_simulations = NUM_SIMULATIONS % NUM_WORKERS

    harris_wins_total = 0
    trump_wins_total = 0
    all_state_results_total = []
    all_electoral_votes_total = []
    all_db_results_total = []

    # Use ProcessPoolExecutor to parallelize the work
    with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = []

        # Distribute the simulation workload across workers
        for i in range(NUM_WORKERS):
            num_simulations = simulations_per_worker
            if i == 0:  # Add the remaining simulations to the first worker
                num_simulations += remaining_simulations
            futures.append(executor.submit(simulate_multiple_times, num_simulations, poll_data, electoral_votes))

        # Collect the results as each worker finishes
        for future in as_completed(futures):
            harris_wins, trump_wins, state_results, electoral_votes_results,all_db_state_values = future.result()  # Use a different variable name
            harris_wins_total += harris_wins
            trump_wins_total += trump_wins
            all_state_results_total.extend(state_results)
            all_electoral_votes_total.extend(electoral_votes_results)  # Correctly collect results here
            all_db_results_total.extend(all_db_state_values)
    uploadDataToDB(all_db_results_total,all_electoral_votes_total,conn)
    conn.close()
    return harris_wins_total, trump_wins_total, all_state_results_total, all_electoral_votes_total,all_db_results_total


if __name__ == '__main__':
    harris_wins, trump_wins, state_results_list, all_electoral_votes_total, results_to_db = run_simulations_parallel()
    
    states_of_interest = [
        'Pennsylvania', 'Wisconsin', 'Michigan', 
        'Nevada', 'Arizona', 'Georgia', 'North Carolina'
    ]
    win_counts = {state: {"Harris": 0, "Trump": 0} for state in states_of_interest}
    win_percents = {state: {"Harris": 0, "Trump": 0} for state in states_of_interest}

    for election_result in state_results_list:
        print("election result:")
        for state, winner, point_diff in election_result:
            if state in states_of_interest:
                win_percents[state][winner]+=point_diff/NUM_SIMULATIONS
                win_counts[state][winner] += 1

    for i, electoral_votes in enumerate(all_electoral_votes_total):
        print(f"Simulation {i+1}: Harris: {electoral_votes['Harris']}, Trump: {electoral_votes['Trump']}")
    for state in states_of_interest:
        harris_wins_state = win_counts[state]["Harris"]
        trump_wins_state = win_counts[state]["Trump"]
        harris_wins_pct = win_percents[state]["Harris"]
        trump_wins_pct = win_percents[state]["Trump"]
        
        if harris_wins_state > 0:
            print(f"{state}: Harris wins {harris_wins_state} times by on avg {harris_wins_pct}")
        if trump_wins_state > 0:
            print(f"{state}: Trump wins {trump_wins_state} times by on avg {trump_wins_pct}")

    print(f"Harris wins: {harris_wins} times")
    print(f"Trump wins: {trump_wins} times")
