import requests
import numpy as np
import pandas as pd
from nba_api.stats.static import teams
from nba_api.stats.endpoints import leaguegamelog, teamestimatedmetrics, leaguehustlestatsteam


#get game ids for todays games
def fetch_games(api_key):
    #the odds api 
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
    
    #add odds and teams for upcoming games to a dataframe
    params = {
        'api_key': api_key,
        'regions': 'us',
        'markets': 'h2h',
        'oddsFormat': 'american',
        'dateFormat': 'iso',
        'bookmakers': ['pinnacle']
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
    else:
        raise Exception(f"Failed to fetch game IDs. Error: {response.text}")
    game_list = []
    for game in data:
        if game['bookmakers']:
            game_id = game['id']
            game_list.append(game_id)

    return game_list

#fetch player prop odds for a given bookmaker an game
def fetch_odds_props(api_key, book, game, prop_type):
    #the odds api 
    url = f'https://api.the-odds-api.com/v4/sports/basketball_nba/events/{game}/odds?'
    
    #add odds and teams for upcoming games to a dataframe
    params = {
        'api_key': api_key,
        'regions': 'us',
        'markets': f'player_{prop_type}',
        'oddsFormat': 'american',
        'dateFormat': 'iso',
        'bookmakers': [book]
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
    else:
        raise Exception(f"Failed to fetch odds data. Error: {response.text}")
    
    if data['bookmakers']:
        outcomes = data['bookmakers'][0]['markets'][0]['outcomes']
    else:
        raise IndexError(f'{book} has incomplete data' )

    # Initialize empty lists to store the data
    player = []
    bet_type = []
    odds = []
    points = []

    # Populate the lists with the data
    for outcome in outcomes:
        player.append(outcome['description'])
        bet_type.append(outcome['name'])
        odds.append(outcome['price'])
        points.append(outcome['point'])

    # Create the DataFrame
    df = pd.DataFrame({
        'player': player,
        'bet_type': bet_type,
        'odds': odds,
        'points': points
    })

    # Reshape the DataFrame to have 'Over' and 'Under' odds as separate columns
    pivot_df = df.pivot(index=['player'], columns='bet_type', values=['odds', 'points']).reset_index()
    pivot_df.columns = ['player', f'over_odds_{book}', f'under_odds_{book}', 'over_points', 'under_points']

    pivot_df['line'] = pivot_df['over_points']
    pivot_df.drop(columns=['over_points', 'under_points'], inplace=True)
    #print(pivot_df)
    return pivot_df

# merge odds from each bookmaker in book_list, for a given game
def fetch_multiple_books(api_key, book_list, game, prop_type):

    # Fetch data for the first book to initialize the DataFrame
    main_df = fetch_odds_props(api_key, book_list[0], game, prop_type)

    # Fetch and combine data for the remaining books
    for book in book_list[1:]:
        book_df = fetch_odds_props(api_key, book, game, prop_type)
        main_df = pd.merge(
            main_df, 
            book_df, 
            on=['player', 'line'], 
            how='outer'
        )

    return main_df

# american odds to implied probability
def odds_to_probability(odds):
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return -odds / (-odds + 100)

def american_to_decimal(odds):
    if odds > 0:
        return (odds / 100) + 1
    else:
        return (100 / odds) + 1

# locate bets with edge > 2.5%
def find_positive_ev_bets(df):
    positive_ev_bets = []
    for index, row in df.iterrows():
        player = row['player']
        line = row['line']
        
        pinnacle_over_odds = row['over_odds_pinnacle']
        pinnacle_under_odds = row['under_odds_pinnacle']
        
        # Calculate implied probabilities for Pinnacle
        pinnacle_over_prob = odds_to_probability(pinnacle_over_odds)
        pinnacle_under_prob = odds_to_probability(pinnacle_under_odds)
        
        for col in df.columns:
            if "over_odds_" in col and col != "over_odds_pinnacle":
                book = col.replace("over_odds_", "")
                book_over_odds = row[col]
                book_over_prob = odds_to_probability(book_over_odds)
                
                # Compare and find positive EV bets for 'Over'
                if book_over_prob < pinnacle_over_prob:
                    positive_ev_bets.append({
                        'player': player,
                        'line': line,
                        'book': book,
                        'bet_type': 'Over',
                        'edge': pinnacle_over_prob - book_over_prob,
                        'pinnacle_odds': pinnacle_over_odds,
                        'other_book_odds': book_over_odds
                    })

            if "under_odds_" in col and col != "under_odds_pinnacle":
                book = col.replace("under_odds_", "")
                book_under_odds = row[col]
                book_under_prob = odds_to_probability(book_under_odds)
                
                # Compare and find positive EV bets for 'Under'
                if book_under_prob < pinnacle_under_prob:
                    positive_ev_bets.append({
                        'player': player,
                        'line': line,
                        'book': book,
                        'bet_type': 'Under',
                        'edge': pinnacle_under_prob - book_under_prob,
                        'pinnacle_odds': pinnacle_under_odds,
                        'other_book_odds': book_under_odds
                    })

    positive_ev_df = pd.DataFrame(positive_ev_bets)
    positive_ev_df = positive_ev_df.sort_values(by='edge', ascending=False).reset_index(drop=True)
    #drop edge lower than 2.5%
    positive_ev_df = positive_ev_df.query('edge > 0.02').reset_index(drop=True)

    return positive_ev_df

#cycle through games today and output sorted df
def main():
    API_KEY = "72f975515f75626b533a11b8354015e6"
    books = ["pinnacle", "fanduel"]
    prop_type = "points" #points, rebounds, assists
    df_list = []

    # Loop through all today's game IDs
    for game_id in fetch_games(API_KEY):
        try:
            # Fetch odds for multiple books
            main_df = fetch_multiple_books(API_KEY, books, game_id, prop_type)
            
            # Find positive EV bets
            ev_df = find_positive_ev_bets(main_df)
            
            if not ev_df.empty:
                df_list.append(ev_df)
                
        except Exception as e:
            print(f"An error occurred for game ID {game_id}: {e}")

    # Concatenate all DataFrames and sort by 'ev' in descending order
    final_df = pd.concat(df_list, ignore_index=True)
    final_df = final_df.sort_values(by='edge', ascending=False).reset_index(drop=True)

    with pd.option_context('display.max_rows', None, 'display.max_columns', None):  # more options can be specified also
        print(final_df)

main()