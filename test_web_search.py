from Tools.web_search import search_web


results = search_web("Python asyncio documentation")

for result in results:
    print("TITLE:", result["title"])
    print("URL:", result["url"])
    print("DESCRIPTION:", result["description"])
    print("-" * 60)