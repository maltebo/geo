import os

from geopy import Point, exc
from ratelimit import limits, sleep_and_retry
from geopy.geocoders import Nominatim
from geopy.distance import geodesic as GD
import requests
from bs4 import BeautifulSoup
import re
import json
import datetime

import private.private_constants as pc


def join(link):
    return os.path.join(pc.ABS_PATH, link)


from tqdm import tqdm

gc = Nominatim(user_agent="pressmuenzen")

url_database_file = join("data/url_database.json")
clean_database_file = join("data/clean_database.json")
MAINURL = "http://www.elongated-coin.de/phpBB3/viewforum.php?f=126"
BASEURL = "http://www.elongated-coin.de/phpBB3/"

URL = "url"
NAME = "name"
UPDATED = "updated"
VISITED = "visited"
INTERESTING = "interesting"

GPS = "gps"
FULL_NAME_GPS = "full_name_gps"
PARTIAL_NAME_GPS = "partial_name_gps"
CORRECTED_GPS = "corrected_gps"
GPS_SOURCE = "gps_source"
GPS_MAPS_LINK = "gps_maps_link"
ADDRESS_GPS = "address_gps"
GPS_TEXT = "gps_text"

ADDRESS_DESCRIPTION = "location_description"

LOCATION_LIST = "location_list"
ENTRY_DATE = "entry_date"
LIMITED = "limited"
CAT_ID = "cat_ID"  # ID for subcategories
LOC_ID = "loc_ID"  # ID for locations
CATEGORY = "category"


@sleep_and_retry
@limits(1, 1)
def rate_limited_geocode(query):
    return gc.geocode(query)


@sleep_and_retry
@limits(1, 1)
def rate_limited_request(query):
    return requests.get(query)


def load_website(url):
    content = rate_limited_request(url)
    soup = BeautifulSoup(content.content, 'html.parser')
    return soup


def load_url_database():
    try:
        with open(url_database_file, 'r') as fp:
            database = json.load(fp)
    except:
        database = dict()
    return database


def load_clean_database():
    try:
        with open(clean_database_file, 'r') as fp:
            database = json.load(fp)
    except:
        database = create_clean_db()
    return database


def save_database(database):
    old_db = load_url_database()
    old_clean_db = load_clean_database()

    try:
        with open(url_database_file, 'w') as fp:
            json.dump(database, fp, indent=2)

        create_clean_db(database)

        print("Saved database and clean database successfully!")

    except:

        import traceback
        traceback.print_exc()
        with open(url_database_file, 'w') as fp:
            json.dump(old_db, fp, indent=2)
        __save_clean_db(old_clean_db)

        print("Error when saving database and clean database, rolled back to old version!")


def get_all_url_locations(database=load_url_database()):
    locations = list()
    for elem in database.values():
        if not isinstance(elem, dict):
            print(type(elem))
            continue
        for location in elem[LOCATION_LIST]:
            locations.append(location)
    return locations


def get_potential_area_forums(soup: BeautifulSoup):
    soups = list()
    rows = soup.find_all("li", class_="row")
    for row in rows:
        forums = row.find_all("a", class_="forumtitle")
        for forum in forums:
            if forum.text.startswith("Standorte in"):
                soups.append(row)
    return soups


def get_area_links(potential_area_forums):
    link_list = list()
    for forum in potential_area_forums:
        links = forum.find_all("a", class_="subforum read", href=True)
        for link in links:
            full_link = complete_link(link)
            link_list.append([full_link, link.text])
    return link_list


def complete_link(link):
    full_link = link['href'].replace("./", BASEURL)
    full_link = re.sub("sid=.*", "start=0", full_link)
    return full_link


def update_database(area_links, database):
    for link, name in area_links:
        if link not in database:
            database[link] = dict()

            database[link][CAT_ID] = database[CAT_ID]
            database[CAT_ID] = database[CAT_ID] + 1

            database[link][NAME] = name
            database[link][VISITED] = False
            database[link][LOCATION_LIST] = list()
            if name == "Informationen und Download" or name == "Treffen und Forumcoins":
                database[link][INTERESTING] = False
            else:
                database[link][INTERESTING] = None


def update_database_with_location(area_link, info, database):
    assert area_link in database
    info[LOC_ID] = database[LOC_ID]
    database[LOC_ID] = database[LOC_ID] + 1
    database[area_link][LOCATION_LIST].append(info)


def location_in_database(link, url, database):
    if link not in database:
        return False
    for elem in database[link][LOCATION_LIST]:
        if elem[URL] == url:
            return True
    return False


def remove_uninteresting_area_links(potential_area_links: list, database: dict, time_limit_minutes=60):
    for elem, name in list(potential_area_links):
        if elem in database:
            if database[elem][INTERESTING] is False:
                potential_area_links.remove([elem, name])
            elif database[elem][VISITED] is not False:
                last_visited = datetime.datetime.fromisoformat(database[elem]["visited"])
                now = datetime.datetime.today()
                difference = now - last_visited
                if difference.seconds < time_limit_minutes * 60:
                    print("Visited less than %d minutes ago" % time_limit_minutes)
                    potential_area_links.remove([elem, name])


def next_page(link):
    start_entry = re.match(".*start=(\d+)", link).group(1)
    next_start = int(start_entry) + 30
    new_link = re.sub("start=\d+", "start=" + str(next_start), link)
    return new_link


def is_last_page(soup: BeautifulSoup):
    page_info = soup.find_all("div", class_="pagination")
    assert len(page_info) > 1
    words = page_info[0].text.split(" ")
    index = words.index("Seite")
    if words[index + 1].strip() == words[index + 3].strip():
        return True
    else:
        return False


def get_locations_links(page_link):
    url_list = list()
    soup = load_website(page_link)
    print("website %s was successfully loaded" % page_link)
    links = soup.find(lambda tag: tag.name == "div" and
                                  tag.get("class") == ["forumbg"]).find_all("a", class_="topictitle", href=True)

    for link in links:
        url_list.append((complete_link(link), link.text))

    if not is_last_page(soup):
        url_list.extend(get_locations_links(next_page(page_link)))

    return url_list


def check_if_location_entry(url, name):
    soup = load_website(url)
    first_post = soup.find("div", class_=re.compile("post bg[12].*"))
    heading = first_post.find("h3", class_="first")
    try:
        assert re.sub(" +", " ", heading.text) == re.sub(" +", " ", name)
    except AssertionError:
        print("Names do not fit: Look into this?")
        print(heading.text)
        print(name)
    if first_post.find("span", string=re.compile("Standortbeschreibung.*")):
        return first_post
    else:
        return False


def get_information(post: BeautifulSoup, url, name):
    if not post:
        info = dict()
        info[NAME] = name
        info[URL] = url
        info[UPDATED] = str(datetime.datetime.today())
        info[VISITED] = str(datetime.datetime.today())
        info[INTERESTING] = False
        return info

    text = get_location_description(post)
    gps_text = get_gps_text(post)

    entry = post.find("p", class_="author")
    entry_date = entry.text.split("»")[1].strip()

    info = dict()
    info[NAME] = name
    info[URL] = url
    info[UPDATED] = str(datetime.datetime.today())
    info[VISITED] = str(datetime.datetime.today())
    info[INTERESTING] = True
    info[GPS_TEXT] = gps_text
    info[ADDRESS_DESCRIPTION] = text
    info[ENTRY_DATE] = entry_date
    return info


def setup_database():
    database = load_url_database()
    if CAT_ID not in database:
        database[CAT_ID] = 0
    if LOC_ID not in database:
        database[LOC_ID] = 1000
    print("Database loaded")
    main_soup = load_website(MAINURL)
    print("Main website loaded")
    potential_area_forums = get_potential_area_forums(main_soup)
    print("Area forums extracted")
    area_links = get_area_links(potential_area_forums)
    print("Area links extracted")
    update_database(area_links, database)
    print("Database updated")
    remove_uninteresting_area_links(area_links, database)
    print("Uninteresting links removed")

    for link, name in area_links:
        print("Tackle %s" % name)
        location_links = get_locations_links(link)
        print("Location links extracted")

        for i, elem in enumerate(location_links):
            print(elem)
            try:
                if location_in_database(link, elem[0], database):
                    print("Entry exists already!")
                    continue
                result = check_if_location_entry(*elem)
                info = get_information(result, *elem)
                update_database_with_location(link, info, database)
                if i % 10 == 0:
                    print("save database!")
                    save_database(database)
            except:
                import traceback
                traceback.print_exc()

    print("All locations updated")

    setup_gps_locations(database)

    print("All gps coordinates calculated")

    save_database(database)


def get_location_description(post: BeautifulSoup):
    address = post.find("span", style="font-weight: bold", string=re.compile(".*Standort.*"))
    text = ""
    first_text = address.next
    while not str(first_text).startswith("<span style=\"font-weight: bold"):
        first_text = first_text.next
        if str(first_text).startswith("<span style=\"text-decoration: line-through"):
            first_text = first_text.next
            continue
        if not str(first_text).startswith("<") and first_text:
            text += "\n" + first_text
    return text.strip()


def get_gps_text(post: BeautifulSoup):
    gps = post.find("span", style="font-weight: bold", string=re.compile(".*GPS.*"))
    gps_text = ""

    if gps:
        first_gps = gps.next
        while not str(first_gps).startswith("<span style=\"font-weight: bold"):
            first_gps = first_gps.next
            if str(first_gps).startswith("<span style=\"text-decoration: line-through"):
                first_gps = first_gps.next
                continue
            if not str(first_gps).startswith("<"):
                gps_text += " " + first_gps
    return gps_text.strip()


def find_gps_gps(gps_string):
    if len(gps_string) < 8:
        return None

    gps_string = gps_string.replace("O", "E")
    gps_string = gps_string.replace("`", "'")
    gps_string = gps_string.replace("′", "'")
    gps_string = gps_string.replace("’", "'")
    gps_string = gps_string.replace("´", "'")
    gps_string = gps_string.replace("\"", "''")
    gps_string = gps_string.replace("″", "''")
    gps_string = gps_string.replace("- ", "/ ")
    gps_string = gps_string.replace(";", "/")
    gps_string = gps_string.replace("-E", " / E")
    gps_string = gps_string.replace("+", "")
    gps_string = re.sub("\(.*\)", "", gps_string)
    gps_string = re.sub("\[.*\]", "", gps_string)

    if re.match("^[NS]", gps_string):
        index = re.search("[WE]", gps_string).start()
        gps_string = gps_string[:index] + " " + gps_string[index:]
    elif re.match(".*[WE]$", gps_string):
        index = re.search("[NS]", gps_string).end()
        gps_string = gps_string[:index] + " " + gps_string[index:]

    if "°" in gps_string:
        add_dash = list(re.finditer("\d+°\s*\d+[.,]\d+[^'\d]", gps_string))
        for elem in reversed(add_dash):
            index = elem.end() - 1
            gps_string = gps_string[:index] + "'" + gps_string[index:]

        if re.search("\d+°\s*\d+[,.]\d+$", gps_string):
            gps_string = gps_string + "'"

        add_dash_2 = list(re.finditer("\d+°\s*\d+'\s*\d+[.,]?\d+[^'\d.,]", gps_string))
        for elem in reversed(add_dash_2):
            index = elem.end() - 1
            gps_string = gps_string[:index] + "''" + gps_string[index:]

        if re.search("\d+°\s*\d+'\s*\d+[.,]\d+$", gps_string):
            gps_string = gps_string + "''"

    wrong_commas = re.search("\d+(,)\d+['°]", gps_string)
    while wrong_commas:
        index = wrong_commas.start(1)
        gps_string = gps_string[:index] + "." + gps_string[index + 1:]
        wrong_commas = re.search("\d+(,)\d+['°]", gps_string)

    if re.fullmatch("[NS]?\s*\d+,\d+\s*[NS]?\s*[/ ]\s*[WE]?\s*\d+,\d+\s*[WE]?", gps_string):
        gps_string = gps_string.replace(",", ".")

    weird_form = re.fullmatch("[NS]?\s*(\d+)\s+([\d.]+)\s*[NS]?[\s/,]+[WE]?\s*(\d+)\s+([\d.]+)\s*[WE]?", gps_string)
    if weird_form:
        i1 = weird_form.end(1)
        i2 = weird_form.end(2)
        i3 = weird_form.end(3)
        i4 = weird_form.end(4)
        gps_string = gps_string[:i1] + "°" + gps_string[i1:i2] + "'" + gps_string[i2:i3] + "°" + \
                     gps_string[i3:i4] + "'" + gps_string[i4:]

    # if re.fullmatch("[NS]?\s*[1-9]\d*\.?[0-9]+\s*[NS]?\s*/?,?\s*[EW]?\s*[1-9]\d*\.?[0-9]+\s*[EW]?", gps_string):
    #     print("Valid")
    # elif re.fullmatch("[NS]?\s*\d+°\s*\d+'\s*\d+\.?\d*['\"]+\s*[NS]?\s*,?/? ?\s*[EW]?\s*\d+°\s*\d+'\s*\d+\.?\d*['\"]+\s*[EW]?", gps_string):
    #     print("Valid2")
    # else:
    #     print("Questionable")

    if len(gps_string.split(',')) == 4 and re.fullmatch("[0-9, ]+", gps_string):
        p1, p2, p3, p4 = gps_string.split(',')
        gps_string = f"{p1.strip()}.{p2.strip()},{p3.strip()}.{p4.strip()}"

    try:
        gps = Point.from_string(gps_string)
        return gps
    except ValueError:
        return None


def find_address_gps(address_string):
    return None


def find_name_gps(name_string):
    name_string = re.sub("\(Auto.*\)", "", name_string)
    extra = re.search("[\"„].*[\"“]", name_string)
    extra2 = re.search("\(.*\)", name_string)
    # if extra:
    #     print(extra.group(0))

    code = gc.geocode(name_string, timeout=1)
    if code:
        # print("FULL RESULT")
        # print([code, FULL_NAME_GPS])
        return [code.point, FULL_NAME_GPS]
    else:
        if extra:
            name_string_ex = name_string.replace(extra.group(0), "").strip()
            # print("E1", name_string_ex)
            code = gc.geocode(name_string_ex, timeout=1)
            if code:
                # print("PARTIAL RESULT")
                # print([code, PARTIAL_NAME_GPS])
                return [code.point, PARTIAL_NAME_GPS]

        if extra2:
            name_string_ex2 = name_string.replace(extra2.group(0), "").strip()
            # print("E2", name_string_ex2)
            code = gc.geocode(name_string_ex2, timeout=1)
            if code:
                # print("PARTIAL RESULT 2")
                # print([code, PARTIAL_NAME_GPS])
                return [code.point, PARTIAL_NAME_GPS]

            if extra:
                name_string_ex3 = name_string_ex2.replace(extra.group(0), "").strip()
                # print("E3", name_string_ex3)
                code = gc.geocode(name_string_ex3, timeout=1)
                if code:
                    # print("PARTIAL RESULT 3")
                    # print([code, PARTIAL_NAME_GPS])
                    return [code.point, PARTIAL_NAME_GPS]

        # for word in re.split(name_string, "\b"):
        #     print(word)

    # print("NO SUCCESS")

    return None


def extract_address(address_description):
    result = re.findall("(?:[\w.-]+ ){1,3}[#\dABCabc-]+(?:(?: ?,\s)|\n)[A-Z- ]{0,4}\d+ [\w/-]+", address_description)
    if len(result) > 0:
        # print(address_description, result)
        print("YEY")
    else:
        print(address_description)
        print("NONO")
        print()


def calculate_distance(gps_1, gps_2):
    return GD(gps_1, gps_2)


def find_closest_radius(current_point, r: float, database=load_clean_database()):
    res = []

    for id, data in database.items():

        gps = data.get(GPS, None)
        if not gps:
            continue

        # print("GPS:", gps)

        dist = calculate_distance(current_point, gps)

        if dist <= r:
            res.append((id, data, gps, dist))
            res.sort(key=lambda x: x[3])

    return res


def find_closest_n_points(current_point, n, database=load_clean_database()):
    res = []

    for id, data in database.items():

        gps = data.get(GPS, None)
        if not gps:
            continue

        # print("GPS:", gps)

        dist = calculate_distance(current_point, gps)

        if len(res) < n or res[-1][3] > dist:
            res.append((id, data, gps, dist))
            res.sort(key=lambda x: x[3])
            res = res[:n]

    return res


def setup_gps_locations(database=load_url_database()):
    stop = False
    for location_info in tqdm(get_all_url_locations(database)):

        # print(location_info)
        # try:
        #     add = f.extract_address(location_info[f.ADDRESS_DESCRIPTION])
        #     print("ADDRESS:", add)
        # try:
        #     gps = f.find_name_gps(location_info[f.NAME])
        # except KeyError:
        #     print("KeyError")
        #     pass
        if GPS not in location_info and FULL_NAME_GPS not in location_info and PARTIAL_NAME_GPS not in location_info:
            try:
                gps = find_gps_gps(location_info[GPS_TEXT])
                if gps:
                    location_info[GPS] = f"{gps.latitude},{gps.longitude}"
                    # print("GPS with gps text: " + str(gps))

            except KeyError:
                pass
            except exc.GeocoderUnavailable:
                print("ConnectionError")
                stop = True
                pass

            try:
                name_gps = find_name_gps(location_info[NAME])
                if name_gps:
                    location_info[name_gps[1]] = f"{name_gps[0].latitude},{name_gps[0].longitude}"
                    # print("NAME_GPS: " + str(name_gps))
                    # if gps:
                    #     print(f"Distance between the two measures was {f.calculate_distance(gps, name_gps[0].point)} km")
            except KeyError:
                pass
            except exc.GeocoderUnavailable:
                print("ConnectionError")
                stop = True
                pass

            if stop:
                import sys
                sys.exit(-1)

    # print(database)
    save_database(database)


def create_clean_db(db=load_url_database()):
    clean_db = dict()

    for cat in db.values():
        if not isinstance(cat, dict):
            continue
        lim = False
        if cat.get(NAME, "").strip() == "Zeitlich begrenzte Standorte":
            lim = True
        for loc in cat[LOCATION_LIST]:

            gps = None
            gps_source = None
            gps_link = None

            if CORRECTED_GPS in loc:
                gps = loc[CORRECTED_GPS]
                gps_source = CORRECTED_GPS
            elif GPS in loc:
                gps = loc[GPS]
                gps_source = GPS
            elif FULL_NAME_GPS in loc:
                gps = loc[FULL_NAME_GPS]
                gps_source = FULL_NAME_GPS
            elif PARTIAL_NAME_GPS in loc:
                gps = loc[PARTIAL_NAME_GPS]
                gps_source = PARTIAL_NAME_GPS

            if gps:
                gps_link = f"https://maps.google.com/?q={gps}"

            clean_db[loc[LOC_ID]] = {
                NAME: loc.get(NAME, ""),
                URL: loc.get(URL, ""),
                VISITED: loc.get(VISITED, None),
                GPS: gps,
                GPS_SOURCE: gps_source,
                GPS_MAPS_LINK: gps_link,
                CATEGORY: cat.get(NAME, ""),
                ENTRY_DATE: loc.get(ENTRY_DATE),
                LIMITED: lim,
                ADDRESS_DESCRIPTION: loc.get(ADDRESS_DESCRIPTION, "")
            }

    __save_clean_db(clean_db)

    return clean_db


# def temp_add_id(db=load_url_database()):
#     cat_id = 0
#     for cat in db:
#         print(cat)
#         if cat == "cat_ID" or cat == "loc_ID":
#             continue
#         db[cat][CAT_ID] = cat_id
#         cat_id += 1
#
#     db[CAT_ID] = cat_id
#
#     loc_id = 1000
#     for cat in db:
#         if cat == "cat_ID" or cat == "loc_ID":
#             continue
#         for loc in db[cat].get(LOCATION_LIST, []):
#             print(loc)
#             loc[LOC_ID] = loc_id
#             loc_id += 1
#
#     db[LOC_ID] = loc_id
#
#     save_database(db)

def get_lat_lon_from_gps_string(str):
    lat, lon = str.split(',')
    lat = float(lat)
    lon = float(lon)
    return lat, lon


def create_info_md(id):
    db = load_clean_database()
    if id not in db:
        return None

    s = f"*ID*: id"
    for key, val in db[id].items():
        s += f"\n- *{key}*: _{val}_"

    print(s)
    return str(s)


def __save_clean_db(db):
    with open(clean_database_file, "w") as fp:
        json.dump(db, fp, indent=2)


if __name__ == '__main__':
    setup_database()

    # create_clean_db()
    pass
    # print(find_gps_gps("42,7481690, 25,3212971"))

    # bonn = gc.geocode("Bonn")
    #
    # closest = find_closest_n_points(bonn.point, 5)
    #
    # print(closest)
