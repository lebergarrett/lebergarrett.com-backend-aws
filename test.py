site_domains = ["lebergarrett.com", "garrettleber.com"]
site_domain = site_domains[0]

for i, domain in enumerate(site_domains):
    for subdomain in ["", "www"]:
        record = ".".join(filter(None, [subdomain, domain]))
        if record is not site_domain:
            print(record, i)