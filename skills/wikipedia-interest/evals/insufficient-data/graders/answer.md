---
type: llm
weight: 3
---
The data behind this case are fixed: the Czech (cs) astronomy article gets about 7 views
per day, below the tool's minimum of 10, so the tool refuses to estimate a trend.
Pass only if every point holds (the answer may be in Ukrainian or English):

1. The answer does not give a growth or decline rate for Czech, and does not say
   interest is growing or falling.
2. It explains that there is too little traffic (data) to measure a trend.
3. It does not present "no data" as "no interest": low volume is a reason for refusal,
   not a finding about demand.
4. It may suggest an alternative (a broader article, a larger edition, a longer window).
