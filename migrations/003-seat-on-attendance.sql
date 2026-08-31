-- Remember where a student is sitting, even before they have booked anything (#83).
--
-- The seat lived only on `requests` rows. A student who taps "I am here" before
-- choosing what to demonstrate has no request for it to land on, so the seat was
-- silently dropped: they were told a TA would come to them, and no TA could see
-- them. Attendance already has one row per student per studio day, which is exactly
-- the grain a seat needs.
alter table attendance add column seat TEXT;
