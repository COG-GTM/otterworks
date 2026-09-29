create table user_preferences.user_preference (user_id varchar(100) not null, email_notifications boolean not null, locale varchar(20) not null, theme varchar(20) not null, primary key (user_id));
