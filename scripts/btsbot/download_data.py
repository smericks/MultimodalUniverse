import os
import argparse
import requests
import zipfile
from tqdm import tqdm


def main(args):
    record_id = "10839691"
    file_names = ["images_v10.zip", "metadata_v10.zip"]

    # Construct the URL to download the file from Zenodo
    urls = [f"https://zenodo.org/record/{record_id}/files/{file_name}" for file_name in file_names]

    if not os.path.exists(args.destination_path):
        os.mkdir(args.destination_path)

    for file_name, url in zip(file_names, urls):
        # Send a GET request to the Zenodo URL to download the file
        response = requests.get(url, stream=True)

        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            # Open a file in binary write mode to save the downloaded content
            with tqdm.wrapattr(open(os.path.join(args.destination_path, file_name), "wb"), "write", miniters=1,
                               desc=file_name, total=int(response.headers.get('content-length'))) as fout:
                for chunk in response.iter_content(chunk_size=4096):
                    fout.write(chunk)
            # with open(os.path.join(args.destination_path, file_name), 'wb') as f:
            #     # Write zip file to destination folder
            #     f.write(response.content)

        # Unzip tar.gz file
        with zipfile.ZipFile(os.path.join(args.destination_path, file_name), "r") as zip_file:
            zip_file.extractall(args.destination_path)

        # Remove tar.gz file
        os.remove(os.path.join(args.destination_path, file_name))

        # Print a success message if the file is downloaded successfully
        print(f"File downloaded successfully to {args.destination_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transfer data from YSE DR1 to user-provided destination folder.")
    parser.add_argument("destination_path", type=str, help="The destination path to download and unzip the data into.",
                        default="./")
    parser.add_argument('-n', '--hyphenate-cols', nargs='+',
                        default=['SPEC_CLASS', 'SPEC_CLASS_BROAD', 'PARSNIP_PRED', 'SUPERRAENN_PRED'])
    args = parser.parse_args()
    main(args)
