from math import exp
from statistics import mean

SCENARIOS={"base":1,"busy":1.25,"festival":1.6}

def estimate(records,scenario):
    positive=[r for r in records if r["changes"]>0]
    anticipated=mean(r["liters"] for r in records[-3:])*SCENARIOS[scenario]
    activation=(len(positive)+1)/(len(records)+2)
    exposure=sum(r["liters"] for r in positive)
    # With insufficient exposure, a one-count / 300 L prior keeps the tail finite.
    average=anticipated*(sum(r["changes"] for r in positive)+1)/(exposure+300)
    pmf=exp(-average)
    quantile=1
    cumulative=1-activation+activation*pmf
    while cumulative<.9 and quantile<10_000:
        pmf*=average/quantile
        cumulative+=activation*pmf
        if cumulative<.9:
            quantile+=1
    upper=0 if 1-activation+activation*exp(-average)>=.9 else quantile
    return {"expected":round(activation*average,4),"upper":upper,"exposure":round(anticipated,2),
        "calibration":{"samples":len(records),"positive":len(positive),"probability":round(activation,4),"conditional_rate":round(average,4)}}
