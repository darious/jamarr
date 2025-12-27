def parse_similar(similar_item):
    if isinstance(similar_item, dict):
        return similar_item.get("name"), similar_item.get("mbid")
    return similar_item, None
