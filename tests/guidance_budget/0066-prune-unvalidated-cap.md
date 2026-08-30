# 0066 - prune the unvalidated cap

follows: 0065
follows-resident-measured: 86_740
follows-total-measured: 433_454
resident-ceiling: 86_700
resident-measured: 86_589
total-ceiling: 433_400
total-measured: 433_368

The opening score no longer needs a phase marker or a separate hard ceiling for
missing calibration. Removing that machinery and its duplicated routing prose
makes the model smaller: absent evidence loses only its weighted calibration
credit, incomplete evidence cannot claim probe credit, and demonstrated failure
keeps the existing safety cap. These lower ceilings record the resulting prune
rather than spending the recovered guidance budget immediately.
