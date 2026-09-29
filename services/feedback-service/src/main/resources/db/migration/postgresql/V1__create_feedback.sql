create table feedback.feedback (id  bigserial not null, created_at timestamp not null, message varchar(2000) not null, rating int4 not null, user_id varchar(100) not null, primary key (id));
