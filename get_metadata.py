import esprima
import json


def get_metadata(script):
    ast = esprima.parseScript(script)
    if ast.type == 'Program' and ast.body:
        statement = ast.body[0]
        if statement and statement.type == 'VariableDeclaration':
            declaration = statement.declarations[0]
            if declaration.type == 'VariableDeclarator':
                right_hand_side = declaration.init
                if right_hand_side and right_hand_side.type == 'Literal':
                    value = right_hand_side.value
    json_data = json.loads(value)
    url = json_data[0][1]['json']['data']['artworkResult']['figures'][0]['deepZoom']['Image']['Url']
    format = json_data[0][1]['json']['data']['artworkResult']['figures'][0]['deepZoom']['Image']['Format']
    tile_size = json_data[0][1]['json']['data']['artworkResult']['figures'][0]['deepZoom']['Image']['TileSize']
    width = json_data[0][1]['json']['data']['artworkResult']['figures'][0]['deepZoom']['Image']['Size']['Width']
    height = json_data[0][1]['json']['data']['artworkResult']['figures'][0]['deepZoom']['Image']['Size']['Height']
    return url, format, tile_size, width, height
