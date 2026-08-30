# 0067 - prune the unvalidated cap

follows: 0066
follows-resident-measured: 86_760
follows-total-measured: 433_474
resident-ceiling: 86_700
resident-measured: 86_609
total-ceiling: 433_400
total-measured: 433_388

The opening score no longer needs a phase marker or a separate hard ceiling for
missing calibration. Removing that machinery and its duplicated routing prose
makes the model smaller: absent evidence loses only its weighted calibration
credit, incomplete evidence cannot claim probe credit, and demonstrated failure
keeps the existing safety cap. These lower ceilings record the resulting prune
rather than spending the recovered guidance budget immediately.
