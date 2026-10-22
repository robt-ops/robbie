#
# THOR Momentum — 30-minute rate of change, in percent
#
# Column settings:  Aggregation = 5 min   |   Extended Hours = OFF
#
# Six 5-minute bars back. At 10:00 this reads the move since 09:30, which
# is the window that matters for opening-auction follow-through.
#
# STATUS: not compiled against thinkorswim. See README verification steps.

def momBars = 6;                           # 6 x 5 min = 30 min

plot Mom = if close[momBars] > 0
           then (close - close[momBars]) / close[momBars] * 100
           else Double.NaN;

Mom.AssignValueColor(
    if Mom >= 1.0 then Color.CYAN
    else if Mom > 0 then Color.GREEN
    else if Mom > -1.0 then Color.RED
    else Color.MAGENTA);
