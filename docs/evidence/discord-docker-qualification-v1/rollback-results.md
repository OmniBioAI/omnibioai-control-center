# Rollback qualification

`ROLLBACK=NOT_VERIFIED`. Current Git HEAD is `f37ce8c952f917f607e9923cbb47dda8b0406a7a`, but the Discord integration source is dirty/untracked and has no legitimate prior source revision in repository history. The locally available Control Center base image predates these Discord changes and is not a compatible prior Discord candidate. No historical candidate image/schema pair meeting the release contract was found in the existing evidence inspected.

No synthetic rollback fixture was executed. Selecting the base image as a rollback target would not test continuity for the actual candidate and would risk misrepresenting G11. No database migration or production data was touched. A reviewed prior Discord candidate, schema compatibility declaration, and disposable migration fixture are prerequisites for meaningful rollback qualification.
