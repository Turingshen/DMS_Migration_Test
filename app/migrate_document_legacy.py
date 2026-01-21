
from flask import session as http_session
import pandas as pd
import app.process as p

def load_data():
    data_df = pd.read_excel('document_data.xlsx')

    # zfill columns if columns exist and values are a number
    zfill_rules = {
        "Documentnumber": 25,
        "Documentpart": 3,
        "Documentversion": 2,
    }
    for col, width in zfill_rules.items():
        if col in data_df.columns:
            data_df[col] = data_df[col].apply(lambda x: str(x).zfill(width) if pd.notnull(x) and str(x).isnumeric() else x)

    return data_df

def start_migrate():
    data_df = load_data()
    response = p.start_worker(data_df)
    return response
