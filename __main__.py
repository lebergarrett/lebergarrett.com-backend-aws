import pulumi
import pulumi_aws as aws

site_name = "lebergarrett"
site_tld = ".com"
site_domain = site_name + site_tld

website_bucket = aws.s3.Bucket(site_name,
    bucket=site_domain,
    acl="public-read",
    website=aws.s3.BucketWebsiteArgs(
        index_document="index.html"
    )
)

cloudfront_oai = aws.cloudfront.OriginAccessIdentity(site_name,
    comment="Allow Cloudfront distribution access to S3 bucket"
)

website_bucket_policy_document = aws.iam.get_policy_document_output(statements=[aws.iam.GetPolicyDocumentStatementArgs(
    principals=[aws.iam.GetPolicyDocumentStatementPrincipalArgs(
        type="AWS",
        identifiers=[cloudfront_oai.iam_arn],
    )],
    actions=[
        "s3:GetObject",
    ],
    resources=[
        website_bucket.arn.apply(lambda arn: f"{arn}/*"),
    ],
)])

website_bucket_policy = aws.s3.BucketPolicy(site_name,
    bucket=website_bucket.id,
    policy=website_bucket_policy_document.json,
)

website_ssl_certificate = aws.acm.Certificate(site_name,
    domain_name=site_domain,
    validation_method="DNS",
    subject_alternative_names=[f"www.{site_domain}"]
)

s3_origin_id = f"{site_name}-S3"

cloudfront_distribution = aws.cloudfront.Distribution(site_name,
    enabled=True,
    aliases=[site_domain, f"www.{site_domain}"],
    default_root_object="index.html",
    is_ipv6_enabled=True,

    default_cache_behavior=aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
        allowed_methods=["GET","HEAD"],
        cached_methods=["GET","HEAD"],
        default_ttl=3600,
        max_ttl=86400,
        target_origin_id=s3_origin_id,
        viewer_protocol_policy="redirect-to-https",
        forwarded_values=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesArgs(
            query_string=False,
            cookies=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesCookiesArgs(
                forward="none",
                whitelisted_names=[]
            ),
        ),
    ),

    origins=[aws.cloudfront.DistributionOriginArgs(
        domain_name=website_bucket.bucket_domain_name,
        origin_id=s3_origin_id,
        s3_origin_config=aws.cloudfront.DistributionOriginS3OriginConfigArgs(
            origin_access_identity=cloudfront_oai.cloudfront_access_identity_path,
        ),
    )],

    restrictions=aws.cloudfront.DistributionRestrictionsArgs(
        geo_restriction=aws.cloudfront.DistributionRestrictionsGeoRestrictionArgs(
            restriction_type="none",
        ),
    ),

    viewer_certificate=aws.cloudfront.DistributionViewerCertificateArgs(
        acm_certificate_arn=website_ssl_certificate.arn,
        minimum_protocol_version="TLSv1.2_2019",
        ssl_support_method="sni-only",
    ),
)

domain_zone = aws.route53.get_zone(name=site_domain)

website_record = aws.route53.Record(site_name,
    zone_id=domain_zone.zone_id,
    name=site_domain,
    type="A",

    aliases=[aws.route53.RecordAliasArgs(
        name=cloudfront_distribution.domain_name,
        zone_id=cloudfront_distribution.hosted_zone_id,
        evaluate_target_health=False,
    )]
)

www_redirect = aws.route53.Record(f"www-{site_name}",
    zone_id=domain_zone.zone_id,
    name=f"www.{site_domain}",
    type="CNAME",
    ttl=300,
    records=[site_domain]
)

# Export the name of the bucket
#pulumi.export('bucket_name', bucket.id)
