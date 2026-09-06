def upload_to_hf_dataset(file_path, dataset_name, token, repo_type="dataset"):
    """
    Upload a file to a Hugging Face dataset repository.

    Args:
        file_path (str): Path to the file to upload
        dataset_name (str): Name of the dataset in format 'username/dataset-name'
        token (str): Hugging Face API token
        repo_type (str): Repository type, defaults to 'dataset'
    """
    from huggingface_hub import HfApi
    import os

    # Initialize the Hugging Face API client
    api = HfApi()

    try:
        # Upload the file to the dataset repository
        api.upload_file(
            path_or_fileobj=file_path,
            path_in_repo=os.path.basename(file_path),  # Use filename as path in repo
            repo_id=dataset_name,
            repo_type=repo_type,
            token=token,
            commit_message=f"Upload {os.path.basename(file_path)}",
            commit_description=f"Automated upload of {os.path.basename(file_path)} to dataset",
        )
        print(f"Successfully uploaded {file_path} to {dataset_name}")
    except Exception as e:
        print(f"Error uploading file: {str(e)}")


def download_from_hf_dataset(file_path, dataset_name, token, repo_type="dataset"):
    """
    Download a file from a Hugging Face dataset repository.

    Args:
        file_path (str): Path in the repository to download from
        dataset_name (str): Name of the dataset in format 'username/dataset-name'
        token (str): Hugging Face API token
        repo_type (str): Repository type, defaults to 'dataset'
    """
    from huggingface_hub import HfApi
    import os

    # Initialize the Hugging Face API client
    api = HfApi()

    try:
        # Download the file from the dataset repository
        api.hf_hub_download(
            repo_id=dataset_name,
            filename=file_path,
            repo_type=repo_type,
            local_dir=".",
            token=token,
        )
        print(f"Successfully downloaded {file_path} from {dataset_name}")
    except Exception as e:
        print(f"Error downloading file: {str(e)}")


def load_hf_dataset(csv_filename, token, dataset_name_input):
    """
    Load a CSV dataset from Hugging Face and return as pandas DataFrame

    Args:
        csv_filename (str): Name of the CSV file in the dataset
        token (str): Hugging Face authentication token

    Returns:
        pandas.DataFrame: DataFrame containing the dataset
    """
    from datasets import load_dataset

    try:
        dataset = load_dataset(
            dataset_name_input, data_files=csv_filename, split="train", token=token
        )
        return dataset.to_pandas()
    except Exception as e:
        print(f"Error loading dataset: {e}")
        return None


def check_file_in_hf_dataset(file_path, dataset_name, token, repo_type="dataset"):
    """
    Check if a file exists in a Hugging Face dataset repository.

    Args:
        file_path (str): Path in the repository to check
        dataset_name (str): Name of the dataset in format 'username/dataset-name'
        token (str): Hugging Face API token
        repo_type (str): Repository type, defaults to 'dataset'

    Returns:
        bool: True if file exists, False otherwise
    """
    from huggingface_hub import HfApi
    import os

    # Initialize the Hugging Face API client
    api = HfApi()

    try:
        # List all files in the repository
        files = api.list_repo_files(
            repo_id=dataset_name, repo_type=repo_type, token=token
        )

        # Check if the file exists in the list
        exists = file_path in files
        print(
            f"File {file_path} {'exists' if exists else 'does not exist'} in {dataset_name}"
        )
        return exists

    except Exception as e:
        print(f"Error checking file: {str(e)}")
        return False


def export_watchlist(df, ticker):
    # outstr=""
    # for index,item in df.iterrows():
    #    outstr = outstr +  item[ticker] + ','
    # return outstr
    return df[ticker].str.cat(sep=", ")


def get_table_download_link(df, ticker, selecteddate, prefix):
    import base64
    import datetime

    b64 = base64.b64encode(export_watchlist(df, ticker).encode()).decode()
    today = (
        str(datetime.datetime.today().year)
        + "-"
        + str("{:02d}".format(datetime.datetime.today().month))
        + "-"
        + str("{:02d}".format(datetime.datetime.today().day))
    )
    href = f'<a href="data:file/txt;base64,{b64}" download="{prefix}_{selecteddate}.txt">Download ! </a>'
    return href

def fetch_news(ticker):
    """Fetch news headlines from finviz for a given ticker"""
    import requests
    from bs4 import BeautifulSoup
    try:
        url = fr"https://finviz.com/stock?t={ticker}&p=d"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, "html.parser")
        print(response.status_code)
        # Find all news containers
        news_containers = soup.find_all(
            "div",
            class_="inline-block pr-5 leading-relaxed"
        )
        
        news_list = []
        for container in news_containers:
            timestamp_span = container.find("span", class_="text-positive whitespace-nowrap pr-2")
            headline_span = timestamp_span.find_next_sibling("span") if timestamp_span else None
            
            if timestamp_span and headline_span:
                headline = headline_span.contents[0].strip()
                finviz_url = fr"https://finviz.com/stock?t={ticker}&p=d"
                news_list.append({
                    "Ticker": ticker,
                    "News Title": headline,
                    "URL": finviz_url
                })
        
        return news_list
    except Exception as e:
        print(f"Error fetching news for {ticker}: {e}")
        return []
