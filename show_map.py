import os

import folium
from folium.plugins import MarkerCluster
from folium.features import DivIcon
import functions as f
from random import randint

import private.private_constants as pc

def join(link):
    return os.path.join(pc.ABS_PATH, link)

def create_map_all_locations():
    loc = []
    for id, data in f.load_clean_database().items():
        if f.GPS in data and data[f.GPS]:
            loc.append([id, data, data[f.GPS], None])

    return create_map(None, loc)


def create_map(origin, locations: list):
    # Create a map
    map = folium.Map()

    # Add markers to the map
    marker_cluster = MarkerCluster().add_to(map)
    for id, location_data, location, dist in locations:
        latitude, longitude = f.get_lat_lon_from_gps_string(location)

        color = 'darkblue'
        if location_data[f.GPS_SOURCE] == f.CORRECTED_GPS:
            color = 'green'
        elif location_data[f.GPS_SOURCE] == f.FULL_NAME_GPS:
            color = 'blue'
        elif location_data[f.GPS_SOURCE] == f.PARTIAL_NAME_GPS:
            color = 'lightblue'

        tooltip = folium.Tooltip(f"ID:\t{id}\nName:\t{location_data[f.NAME]}")

        popup = create_popup(id, location_data, dist)

        marker = folium.Marker(location=[latitude, longitude],
                               popup=popup,
                               tooltip=tooltip,
                               icon=folium.Icon(color=color))
        marker.add_to(marker_cluster)

        # label = f"{i+1}"
        #
        # marker = folium.map.Marker(
        #     [latitude, longitude],
        #     icon=DivIcon(
        #         icon_size=(20, 20),
        #         icon_anchor=(0, 0),
        #         html='<div style="font-size: 24pt">%s</div>' % label,
        #     )
        # )
        # marker.add_to(marker_cluster)

    if origin:
        marker = folium.Marker([origin.latitude, origin.longitude],
                               popup=folium.Popup("<h2>Standort</h2>", show=True),
                               icon=folium.Icon(color='red'))
        marker.add_to(marker_cluster)

        o_point = [origin.latitude, origin.longitude]

        for _, _, location, _ in locations:
            p = f.get_lat_lon_from_gps_string(location)
            folium.PolyLine([o_point, p], color='gray', weight=1, opacity=0.5).add_to(marker_cluster)

    # Calculate the bounding box for all locations
    bounds = [[float('inf'), float('inf')], [float('-inf'), float('-inf')]]
    for _, _, location, _ in locations:
        latitude, longitude = f.get_lat_lon_from_gps_string(location)
        bounds[0][0] = min(bounds[0][0], latitude)
        bounds[0][1] = min(bounds[0][1], longitude)
        bounds[1][0] = max(bounds[1][0], latitude)
        bounds[1][1] = max(bounds[1][1], longitude)

    if origin:
        latitude, longitude = origin.latitude, origin.longitude
        bounds[0][0] = min(bounds[0][0], latitude)
        bounds[0][1] = min(bounds[0][1], longitude)
        bounds[1][0] = max(bounds[1][0], latitude)
        bounds[1][1] = max(bounds[1][1], longitude)

    # Set the map's view to fit the calculated bounds
    map.fit_bounds(bounds)

    os.makedirs(join("temp_data"), exist_ok=True)
    link = join(f"temp_data/map_{randint(0, 2147483647)}.html")

    assert os.path.isfile(link)

    # Save the map as an image
    with open(link, 'wb') as fp:
        map.save(fp)

    return link, locations_to_string(origin, locations)


def create_popup(id, location_data, dist):
    warning = ""
    if location_data[f.LIMITED]:
        warning = "<p><em><strong>WARNUNG:</strong> M&ouml;glicherweise nur zeitlich begrenzt verf&uuml;gbar!</em></p>\n"

    description = location_data[f.ADDRESS_DESCRIPTION]
    if len(description) > 200:
        description = description[:200] + " ... (read on website)"

    dist_str = ""
    if dist:
        dist_str = f"<p><strong>DISTANZ:</strong> {round(dist.km, 1)} km</p>\n"

    text = f"""<h2><strong>{location_data[f.NAME]}</strong></h2>
{warning}<p><strong>ID:</strong> {id}</p>
<p><strong>LINK ZUM FORUM:</strong> <a href="{location_data[f.URL]}" target="_blank">link</a></p>
<p><strong>BESCHREIBUNG:</strong> {description}</p>
{dist_str}<p><strong>LINK ZU GOOGLE MAPS:</strong> <a href="{location_data[f.GPS_MAPS_LINK]}" target="_blank">link</a></p>
<p><strong>EINGETRAGEN AM:</strong> {location_data[f.ENTRY_DATE]}</p>"""

    popup = folium.Popup(text)

    return popup


def locations_to_string(origin, locations):
    s = ""
    if origin:
        s += f"*Eingegebener Standort*: {origin.address}\n"
    for id, location_data, location, dist in locations[:15]:
        s += f"\n*{id}*: {location_data[f.NAME]}"
        if dist is not None:
            s += f" ({round(dist.km, 1)} km)"

    if len(locations) > 15:
        s += f"\n... (nur die ersten 15 Einträge werden angezeigt)"

    return s

# # Use Selenium and webdrivers to take a screenshot
# from selenium import webdriver
#
# # Set the path to your webdriver executable (e.g., chromedriver)
# webdriver_path = "path/to/webdriver/executable"
#
# # Set the path where you want to save the screenshot image
# screenshot_path = "path/to/save/screenshot.png"  # or screenshot.jpg
#
# # Create a webdriver instance
# driver = webdriver.Chrome(executable_path=webdriver_path)
#
# # Open the HTML map file in the webdriver
# driver.get(f"file://{map.save('map.html')}")
#
# # Take a screenshot of the map
# driver.save_screenshot(screenshot_path)
#
# # Close the webdriver
# driver.quit()
