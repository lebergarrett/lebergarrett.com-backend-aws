import json
import os
import pulumi
import pulumi_aws as aws
import tldextract

# Pull in config from "./Pulumi.<stack>.yaml"
config = pulumi.Config()
site_domains = config.require_object('domains')

split_domain = tldextract.extract(site_domains[0])
site_domain = site_domains[0]
site_name = '.'.join(filter(None, split_domain[:2])) # Get all except TLD and rejoin
site_tld = split_domain[-1] # TLD is last element

website_bucket = aws.s3.Bucket(site_name,
    bucket=site_domain,
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

domain_alt_names = [[".".join(filter(None, [subdomain, domain])) for domain in site_domains] for subdomain in ["", "www"]]
domain_alt_names = [item for sublist in domain_alt_names for item in sublist]
domain_alt_names.remove(site_domain)

website_ssl_certificate = aws.acm.Certificate(site_name,
    domain_name=site_domain,
    validation_method="DNS",
    subject_alternative_names=domain_alt_names,
)

s3_origin_id = f"{site_name}-S3"

cloudfront_distribution = aws.cloudfront.Distribution(site_name,
    enabled=True,
    aliases=[site_domain] + domain_alt_names,
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

domain_zones = []
for i, domain in enumerate(site_domains):
    domain_zones.append(aws.route53.get_zone(name=domain))

records = []
for i, domain in enumerate(site_domains):
    records.append(aws.route53.Record(domain,
        zone_id=domain_zones[i].zone_id,
        name=site_domain,
        type="A",

        aliases=[aws.route53.RecordAliasArgs(
            name=cloudfront_distribution.domain_name,
            zone_id=cloudfront_distribution.hosted_zone_id,
            evaluate_target_health=False,
        )]
    ))

redirects = []
for i, domain in enumerate(site_domains):
    redirects.append(aws.route53.Record(f"www.{domain}",
        zone_id=domain_zones[i].zone_id,
        name=f"www.{domain}",
        type="CNAME",
        ttl=300,
        records=[domain]
    ))

# ---------- Visitors App ----------
app_name = "visitors-app"

visitors_table = aws.dynamodb.Table(app_name,
    name=f"{site_name}-visitors",
    billing_mode="PROVISIONED",
    read_capacity=1,
    write_capacity=1,
    hash_key="website",

    attributes=[
        aws.dynamodb.TableAttributeArgs(
            name="website",
            type="S",
        )
    ]
)

iam_for_lambda = aws.iam.Role(app_name, assume_role_policy="""{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Action": "sts:AssumeRole",
            "Principal": {
                "Service": "lambda.amazonaws.com"
            },
            "Effect": "Allow",
            "Sid": ""
        }
    ]
}
""")

PATH_TO_SOURCE_CODE = "./lambda_function"

# The Lambda Function source code itself needs to be zipped up into an
# archive, which we create using the pulumi.AssetArchive primitive.
assets = {}
for file in os.listdir(PATH_TO_SOURCE_CODE):
    location = os.path.join(PATH_TO_SOURCE_CODE, file)
    asset = pulumi.FileAsset(path=location)
    assets[file] = asset

archive = pulumi.AssetArchive(assets=assets)

visitors_lambda = aws.lambda_.Function(app_name,
    code=archive,
    role=iam_for_lambda.arn,
    handler="main.lambda_handler",
    runtime="python3.8",
)

def create_iam_role_policy(table_arn):
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Action": ["dynamodb:UpdateItem"],
            "Effect": "Allow",
            "Resource": table_arn,
        }]
    })

iam_role_policy = aws.iam.RolePolicy(app_name,
    role=iam_for_lambda.id,
    policy=visitors_table.arn.apply(create_iam_role_policy)
)

api_gateway = aws.apigateway.RestApi(app_name)

api_resource = aws.apigateway.Resource(app_name,
    rest_api=api_gateway.id,
    parent_id=api_gateway.root_resource_id,
    path_part="getcount",
)

api_method = aws.apigateway.Method(app_name,
    rest_api=api_gateway.id,
    resource_id=api_resource.id,
    http_method="ANY",
    authorization="NONE",
)

api_integration = aws.apigateway.Integration(app_name,
    opts=pulumi.ResourceOptions(depends_on=[visitors_lambda]),
    rest_api=api_gateway.id,
    resource_id=api_method.resource_id,
    http_method=api_method.http_method,
    integration_http_method="POST",
    type="AWS_PROXY",
    uri=visitors_lambda.invoke_arn,
)

api_deployment = aws.apigateway.Deployment(app_name,
    opts=pulumi.ResourceOptions(depends_on=[api_integration]),
    rest_api=api_gateway.id,
    stage_name="prod",
)

lambda_permission = aws.lambda_.Permission(app_name,
    statement_id="AllowAPIGatewayInvoke",
    action="lambda:InvokeFunction",
    function=visitors_lambda.name,
    principal="apigateway.amazonaws.com",
    source_arn=api_gateway.execution_arn.apply(lambda arn: f"{arn}/*/*")
)
# Export the api endpoint
pulumi.export('Api Endpoint', api_deployment.invoke_url)
pulumi.export('Api Path', api_resource.path_part)
