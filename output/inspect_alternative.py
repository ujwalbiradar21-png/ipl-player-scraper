
import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.ipl-stats.com"
SEASON_URL = f"{BASE_URL}/season/2025/stats"
OUTPUT_DIR = Path(__file__).resolve().parent

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
})


def normalize(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()



def extract_array(html, name):
    """Extract a JSON array from the embedded page data."""
    decoder = json.JSONDecoder()

    # Try the normal JSON property format first.
    patterns = [
        f'"{name}":',
        f'\\"{name}\\":',
    ]

    for pattern in patterns:
        position = html.find(pattern)

        while position != -1:
            start = position + len(pattern)

            # Skip whitespace before the array.
            while start < len(html) and html[start].isspace():
                start += 1

            if start < len(html) and html[start] == "[":
                try:
                    data, _ = decoder.raw_decode(html[start:])
                    if isinstance(data, list):
                        print(f"Found {name}: {len(data)} records")
                        return data
                except json.JSONDecodeError:
                    pass

            position = html.find(pattern, position + 1)

    # Try decoding the HTML after unescaping embedded quotes.
    unescaped_html = html.replace('\\"', '"')
    marker = f'"{name}"'
    position = unescaped_html.find(marker)

    if position != -1:
        start = unescaped_html.find("[", position + len(marker))
        if start != -1:
            try:
                data, _ = decoder.raw_decode(unescaped_html[start:])
                if isinstance(data, list):
                    print(f"Found {name}: {len(data)} records")
                    return data
            except json.JSONDecodeError:
                pass

    raise ValueError(
        f"Could not extract {name}. The page data format may have changed."
    )


def number(value):
    if value is None:
        return None

    value = str(value).strip().replace(",", "")
    if not value or value in {"-", "—", "–", "N/A"}:
        return None

    try:
        result = float(value)
        return int(result) if result.is_integer() else result
    except ValueError:
        return None


def get_stat(soup, label_text):
    """Read a value displayed beside a profile-stat label."""
    for label in soup.find_all("span"):
        if label.get_text(" ", strip=True) == label_text:
            parent = label.parent
            spans = parent.find_all("span", recursive=False)

            for span in reversed(spans):
                if span is not label:
                    value = span.get_text(" ", strip=True)
                    if value:
                        return value

    return None


def get_image_url(soup):
    """Return an image URL only if the page actually provides one."""
    meta = soup.find("meta", property="og:image")
    if meta and meta.get("content"):
        return urljoin(BASE_URL, meta["content"])

    image = soup.find("img", src=True)
    if image:
        return urljoin(BASE_URL, image["src"])

    return None


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching IPL 2025 statistics page...")
    response = session.get(SEASON_URL, timeout=30)
    response.raise_for_status()
    
    html = response.text

    print("HTTP status:", response.status_code)
    print("Page title:", BeautifulSoup(html, "html.parser").title)
    print("HTML length:", len(html))
    print("Contains battingStats:", "battingStats" in html)
    print("Contains batting stats text:", "Batting" in html)

    

    batting = extract_array(html, "battingStats")
    bowling = extract_array(html, "bowlingStats")
    
    print("\nSample batting record:")
    print(json.dumps(batting[0], indent=2))

    print("\nSample bowling record:")
    print(json.dumps(bowling[0], indent=2))

    soup = BeautifulSoup(html, "html.parser")

    # Get actual profile links from the page instead of guessing URLs.
    profile_urls = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if re.match(r"^/player/[^/]+/2025/?$", href):
            name = anchor.get_text(" ", strip=True)
            if name:
                profile_urls[normalize(name)] = urljoin(BASE_URL, href)

    players = {}

    # Build the batting records.
    for item in batting:
        name = item.get("player_name") or item.get("name")
        team = item.get("team")

        if not name:
            continue

        key = (normalize(name), normalize(team))
        players[key] = {
            "player_name": name,
            "team": team,
            "player_image_url": None,
            "matches": item.get("matches"),
            "innings": None,
            "runs": number(item.get("runs")),
            "batting_balls": number(item.get("balls")),
            "batting_average": None,
            "batting_strike_rate": None,
            "fours": number(item.get("fours")),
            "sixes": number(item.get("sixes")),
            "high_score": number(item.get("high_score")),
            "wickets": None,
            "runs_conceded": None,
            "bowling_balls": None,
            "bowling_overs": None,
            "bowling_average": None,
            "bowling_economy": None,
            "bowling_strike_rate": None,
            "profile_url": profile_urls.get(normalize(name)),
        }

    # Merge bowling records using player name and team.
    for item in bowling:
        name = item.get("player_name") or item.get("name")
        team = item.get("team")

        if not name:
            continue

        key = (normalize(name), normalize(team))

        if key not in players:
            players[key] = {
                "player_name": name,
                "team": team,
                "player_image_url": None,
                "matches": item.get("matches"),
                "innings": None,
                "runs": None,
                "batting_balls": None,
                "batting_average": None,
                "batting_strike_rate": None,
                "fours": None,
                "sixes": None,
                "high_score": None,
                "profile_url": profile_urls.get(normalize(name)),
            }

        row = players[key]
        row["bowling_matches"] = number(item.get("matches"))
        row["wickets"] = number(item.get("wickets"))
        row["runs_conceded"] = number(item.get("runs_conceded"))
        row["bowling_balls"] = number(item.get("balls"))
        if row["batting_balls"] is not None and row["batting_balls"] > 0:
            row["batting_strike_rate"] = round(
        row["runs"] / row["batting_balls"] * 100, 2
    )
    else:
        row["batting_strike_rate"] = None

    # Visit profiles to collect extra statistics where available.
    rows = list(players.values())
    failures = []

    for index, row in enumerate(rows, start=1):
        url = row.get("profile_url")

        if url:
            try:
                profile_response = session.get(url, timeout=20)
                profile_response.raise_for_status()
                profile = BeautifulSoup(
                    profile_response.text, "html.parser"
                )

                value = get_stat(profile, "Matches")
                if value is not None:
                    row["matches"] = number(value)

                value = get_stat(profile, "Runs")
                if value is not None:
                    row["runs"] = number(value)

                value = get_stat(profile, "Avg")
                if value is not None:
                    row["batting_average"] = number(value)

                value = get_stat(profile, "SR")
                if value is not None:
                    row["batting_strike_rate"] = number(value)

                value = get_stat(profile, "High Score")
                if value is not None:
                    row["high_score"] = number(value)

                value = get_stat(profile, "Fours / Sixes")
                if value:
                    parts = re.split(r"\s*/\s*", value)
                    if len(parts) == 2:
                        row["fours"] = number(parts[0])
                        row["sixes"] = number(parts[1])

                value = get_stat(profile, "Wickets / Economy")
                if value:
                    parts = re.split(r"\s*/\s*", value)
                    if len(parts) == 2:
                        if row.get("wickets") is None:
                            row["wickets"] = number(parts[0])
                        if parts[1] not in {"-", "—", ""}:
                            row["bowling_economy"] = number(parts[1])

                row["player_image_url"] = get_image_url(profile)

            except (requests.RequestException, ValueError) as error:
                failures.append({
                    "player_name": row["player_name"],
                    "url": url,
                    "error": str(error),
                })
        else:
            failures.append({
                "player_name": row["player_name"],
                "url": None,
                "error": "Profile link not found on the season page",
            })

        # Calculate values only when the required data exists.
        runs = row.get("runs")
        batting_balls = row.get("batting_balls")

        if row.get("batting_strike_rate") is None:
            row["batting_strike_rate"] = (
                round(runs / batting_balls * 100, 2)
                if runs is not None and batting_balls
                else None
            )

        balls = row.get("bowling_balls")
        wickets = row.get("wickets")
        conceded = row.get("runs_conceded")

        if balls is not None:
            row["bowling_overs"] = f"{balls // 6}.{balls % 6}"

        if row.get("bowling_average") is None:
            row["bowling_average"] = (
                round(conceded / wickets, 2)
                if conceded is not None and wickets
                else None
            )

        if row.get("bowling_economy") is None:
            row["bowling_economy"] = (
                round(conceded * 6 / balls, 2)
                if conceded is not None and balls
                else None
            )

        if row.get("bowling_strike_rate") is None:
            row["bowling_strike_rate"] = (
                round(balls / wickets, 2)
                
                if balls is not None and wickets
                else None
            )

        if index % 25 == 0 or index == len(rows):
            print(f"Processed profiles: {index}/{len(rows)}")

        # Be considerate to the source website.
        time.sleep(0.15)

    # Export the combined data.
    json_path = OUTPUT_DIR / "ipl_2025_players.json"
    csv_path = OUTPUT_DIR / "ipl_2025_players.csv"
    failures_path = OUTPUT_DIR / "profile_failures.json"

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(rows, file, indent=2, ensure_ascii=False)

    fieldnames = list(dict.fromkeys(
        field for row in rows for field in row.keys()
    ))
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with failures_path.open("w", encoding="utf-8") as file:
        json.dump(failures, file, indent=2, ensure_ascii=False)

    print("\nScraping finished.")
    print(f"Batting leaderboard records: {len(batting)}")
    print(f"Bowling leaderboard records: {len(bowling)}")
    print(f"Combined player records: {len(rows)}")
    print(f"Profile requests without usable results: {len(failures)}")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    print(f"Profile report: {failures_path}")


if __name__ == "__main__":
    main()

