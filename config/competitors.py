from database.models import CompetitorConfig

# Declarative config: competitors are defined as Python objects, not a YAML/JSON file.
# Advantage: you can add logic here (e.g., conditionally disable a company) without
# writing a parser. Disadvantage vs YAML: non-technical users can't edit it easily.
# In a production system you'd store this in a database table instead so users can
# add companies through a UI — but for a local learning project, this is clean and clear.
COMPETITORS: list[CompetitorConfig] = [
    CompetitorConfig(
        name="Razorpay",
        slug="razorpay",          # used as a DB key and in log messages; must be unique
        website_url="https://razorpay.com",
        careers_url="https://razorpay.com/jobs/",
        github_org="razorpay",    # the GitHub organization name (case-sensitive)
        # OR/AND logic works in Google News RSS queries just like a search engine
        news_query="Razorpay product launch OR funding OR partnership",
    ),
    CompetitorConfig(
        name="Zepto",
        slug="zepto",
        website_url="https://www.zeptonow.com",
        careers_url="https://www.zeptonow.com/careers",
        github_org=None,          # Zepto has no public GitHub org — scraper will skip github
        news_query="Zepto quick commerce OR funding OR expansion OR dark store",
    ),
    CompetitorConfig(
        name="PhonePe",
        slug="phonepe",
        website_url="https://www.phonepe.com",
        careers_url="https://careers.phonepe.com",
        github_org="PhonePe",
        news_query="PhonePe UPI OR product OR acquisition OR partnership",
    ),
    CompetitorConfig(
        name="Meesho",
        slug="meesho",
        website_url="https://meesho.com",
        careers_url="https://meesho.com/jobs",
        github_org="Meesho",
        news_query="Meesho social commerce OR funding OR new feature OR seller",
    ),
]
