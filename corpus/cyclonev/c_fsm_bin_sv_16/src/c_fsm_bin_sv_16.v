module c_fsm_bin_sv_16 (input logic clk, rst, go, alt, output logic done, odd);
  typedef enum logic [3:0] {S0 = 4'd0, S1 = 4'd1, S2 = 4'd2, S3 = 4'd3, S4 = 4'd4, S5 = 4'd5, S6 = 4'd6, S7 = 4'd7, S8 = 4'd8, S9 = 4'd9, S10 = 4'd10, S11 = 4'd11, S12 = 4'd12, S13 = 4'd13, S14 = 4'd14, S15 = 4'd15} state_t;
  state_t st, nx;
  always_comb begin
    nx = S0;
    case (st)
      S0: begin
        if (go) nx = S1;
        else nx = S0;
      end
      S1: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S2;
        else nx = S1;
      end
      S2: begin
        if (go) nx = S3;
        else nx = S2;
      end
      S3: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S4;
        else nx = S3;
      end
      S4: begin
        if (go) nx = S5;
        else nx = S4;
      end
      S5: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S6;
        else nx = S5;
      end
      S6: begin
        if (go) nx = S7;
        else nx = S6;
      end
      S7: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S8;
        else nx = S7;
      end
      S8: begin
        if (go) nx = S9;
        else nx = S8;
      end
      S9: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S10;
        else nx = S9;
      end
      S10: begin
        if (go) nx = S11;
        else nx = S10;
      end
      S11: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S12;
        else nx = S11;
      end
      S12: begin
        if (go) nx = S13;
        else nx = S12;
      end
      S13: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S14;
        else nx = S13;
      end
      S14: begin
        if (go) nx = S15;
        else nx = S14;
      end
      S15: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S0;
        else nx = S15;
      end
      default: nx = S0;
    endcase
  end
  always_ff @(posedge clk) if (rst) st <= S0; else st <= nx;
  assign done = (st == S15);
  assign odd = (st == S1) | (st == S3) | (st == S5) | (st == S7) | (st == S9) | (st == S11) | (st == S13) | (st == S15);
endmodule
