import pandas as pd
import sqlite3
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def DEBUG_graphPolls(stateName):
    conn = sqlite3.connect('polling_data.db')
    
    # Query to select national polls and calculate the weighted average based on numeric_grade
    query = '''
    SELECT end_date, 
           SUM(harris_pct * numeric_grade) / SUM(numeric_grade) AS weighted_harris_pct, 
           SUM(trump_pct * numeric_grade) / SUM(numeric_grade) AS weighted_trump_pct
    FROM polls
    WHERE state = ?
    GROUP BY end_date
    HAVING SUM(numeric_grade) > 0  -- Ensure there is a valid grade for the weighting
    ORDER BY end_date
    '''
    
    # Execute the query with the stateName parameter
    pollData = pd.read_sql_query(query, conn, params=[stateName])
    conn.close()

    # Convert end_date to datetime
    pollData['end_date'] = pd.to_datetime(pollData['end_date'])
    
    # Set end_date as index
    pollData.set_index('end_date', inplace=True)

    # Resample to have daily data, including missing days
    pollData = pollData.resample('D').mean()

    # Interpolate missing values (lerp)
    pollData['weighted_harris_pct'] = pollData['weighted_harris_pct'].interpolate(method='linear')
    pollData['weighted_trump_pct'] = pollData['weighted_trump_pct'].interpolate(method='linear')

    # Plotting
    plt.figure(figsize=(12, 6))
    plt.plot(pollData.index, pollData['weighted_harris_pct'], marker='o', label='Kamala Harris', color='blue')
    plt.plot(pollData.index, pollData['weighted_trump_pct'], marker='o', label='Donald Trump', color='red')

    plt.title('Weighted National Polls for Kamala Harris and Donald Trump (Averaged and Interpolated by Date)')
    plt.xlabel('Date')
    plt.ylabel('Percentage')
    plt.ylim(0, 100)  # Set y-axis limits
    plt.xticks(rotation=45)

    # Customize x-axis to start at the earliest and end at the latest end_date
    earliest_date = pollData.index.min()
    latest_date = pollData.index.max()
    plt.xlim(earliest_date, latest_date)

    # Customize x-axis ticks to show more points
    ax = plt.gca()  # Get current axis
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))  # Set major ticks every week
    ax.xaxis.set_minor_locator(mdates.DayLocator(interval=1))  # Set minor ticks every day
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))  # Format dates (e.g., "Sep 26")

    plt.legend()
    plt.grid()
    plt.tight_layout()
    
    plt.show()

def pullSpecialPCTS():
    conn = sqlite3.connect('polling_data.db')
    cursor = conn.cursor()
    
    # Query to get average national_harris and national_trump for each date in the range
    cursor.execute(f"SELECT AVG(national_Trump) FROM simulations ORDER BY simulation_date DESC LIMIT 100")
    trump_avg = cursor.fetchone()
    conn.close()
    return trump_avg


df=pullSpecialPCTS()
print(df)
