# Chapter One: Testing the Builder

This paragraph exercises **bold**, *italic*, `inline code` and a [link](https://example.com).

## A table

| Component | Purpose | Notes |
|---|---|---|
| PRBC | Packed red blood cells | Most commonly requested |
| FFP | Fresh frozen plasma | Compatibility runs the other way |

*Table 1. Blood components.*

## Code

```python
def evaluate_batch_eligibility(status, available_units, expires_at, now):
    # Fails closed: anything ambiguous is ineligible rather than assumed usable.
    if expires_at is None:
        return EligibilityResult(False, ("MISSING_EXPIRY_DATE",))
    return EligibilityResult(expires_at > now and available_units > 0 and status == "AVAILABLE")
```

*Listing 1. Eligibility, simplified.*

:::key The rule this encodes
Unknown must stay unknown.
:::

## A diagram

```diagram
type: layered
title: Request path
layer Browser
node ui React application style=user
layer Edge
node cf CloudFront style=aws
node api API Gateway style=aws
layer Compute
node fn Lambda handler style=aws
layer Data
node ddb DynamoDB style=data
edge ui -> cf
edge cf -> api
edge api -> fn
edge fn -> ddb query
```

# Chapter Two: Sequences

```diagram
type: sequence
title: Verifying a donation
actor staff Camp staff
actor api API
actor db DynamoDB
msg staff -> api verify
msg api -> db transaction
msg db -> api committed
note Keyed on donation id, so a replay cannot double-credit.
```

Closing paragraph.
